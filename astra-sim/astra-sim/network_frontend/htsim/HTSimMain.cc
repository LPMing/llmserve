/******************************************************************************
This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
*******************************************************************************/

#include "HTSimNetworkApi.hh"
#include "astra-sim/common/Logging.hh"
#include "common/CmdLineParser.hh"
#include "HTSimSession.hh"
#include <astra-network-analytical/common/EventQueue.h>
#include <astra-network-analytical/common/NetworkParser.h>
#include <astra-network-analytical/congestion_unaware/Helper.h>
#include <memory_backend/analytical/AnalyticalMemory.hh>
#include <algorithm>
#include <cstdlib>
#include <limits>
#include <string>
#include <vector>

using namespace HTSim;

namespace {

void htsim_idle_wakeup(void*) {}

}

int main(int argc, char* argv[]) {
    // Parse command line arguments
    auto cmd_line_parser = CmdLineParser(argv[0]);
    cmd_line_parser.get_options().add_options()(
        "htsim-proto", "HTSim Network Protocol [tcp]",
        cxxopts::value<HTSimProto>()->default_value("tcp"));
    cmd_line_parser.parse(argc, argv);

    // Get command line arguments
    const auto workload_configuration = cmd_line_parser.get<std::string>("workload-configuration");
    const auto comm_group_configuration =
        cmd_line_parser.get<std::string>("comm-group-configuration");
    const auto system_configuration = cmd_line_parser.get<std::string>("system-configuration");
    const auto memory_configuration =
        cmd_line_parser.get<std::string>("memory-configuration");
    const auto network_configuration = cmd_line_parser.get<std::string>("network-configuration");
    const auto logging_configuration = cmd_line_parser.get<std::string>("logging-configuration");
    const auto num_queues_per_dim = cmd_line_parser.get<int>("num-queues-per-dim");
    const auto comm_scale = cmd_line_parser.get<double>("comm-scale");
    const auto injection_scale = cmd_line_parser.get<double>("injection-scale");
    const auto rendezvous_protocol = cmd_line_parser.get<bool>("rendezvous-protocol");
    const auto proto = cmd_line_parser.get<HTSimProto>("htsim-proto");

    AstraSim::LoggerFactory::init(logging_configuration);

    // Generate topology
    const auto network_parser = NetworkParser(network_configuration);
    const auto topology = construct_topology(network_parser);

    // Get topology information
    const auto npus_count = topology->get_npus_count();
    const auto npus_count_per_dim = topology->get_npus_count_per_dim();
    const auto dims_count = topology->get_dims_count();

    // Set up Network API
    HTSimNetworkApi::set_topology(topology);
    auto completion_tracker = std::make_shared<CompletionTracker>(npus_count);
    HTSimNetworkApi::set_completion_tracker(completion_tracker);

    // Create ASTRA-sim related resources
    auto network_apis = std::vector<std::unique_ptr<HTSimNetworkApi>>();
    const auto memory_api =
        std::make_unique<Analytical::AnalyticalMemory>(memory_configuration);
    auto memory_apis = std::vector<AstraSim::AstraMemoryAPI*>();
    memory_apis.push_back(memory_api.get());
    auto systems = std::vector<Sys*>();

    auto queues_per_dim = std::vector<int>();
    for (auto i = 0; i < dims_count; i++) {
        queues_per_dim.push_back(num_queues_per_dim);
    }

    for (int i = 0; i < npus_count; i++) {
        // create network and system
        auto network_api = std::make_unique<HTSimNetworkApi>(i);
        auto* const system =
            new Sys(i, workload_configuration, comm_group_configuration, system_configuration,
                    memory_apis, network_api.get(), npus_count_per_dim, queues_per_dim,
                    injection_scale, comm_scale, rendezvous_protocol);

        // push back network and system
        network_apis.push_back(std::move(network_api));
        systems.push_back(system);
    }

    // Get HTSim opts
    int htsim_argc = 0;
    char** htsim_argv = NULL;
    for (int i = 0; i < argc; i++) {
        if (std::string(argv[i]) == "--htsim_opts") {
            htsim_argc = argc - i;
            htsim_argv = argv + i;
        }
    }

    // Report HTSim opts
    for (int i = 0; i < htsim_argc; i++) {
        std::cout << htsim_argv[i] << " ";
    }
    std::cout << std::endl;

    // Initialize HTSim session
    HTSimNetworkApi::htsim_info.nodes = npus_count;
    // Choose protocol
    auto& ht = HTSimSession::init(&HTSimNetworkApi::htsim_info, htsim_argc, htsim_argv, proto);

    // Initiate the first serving round.  Unlike the original one-shot HTSim
    // driver, the serving frontend supplies one workload graph per scheduler
    // iteration through the stdin handshake below.
    ht.set_endtime_infinite();
    auto all_ranks = std::vector<int>();
    all_ranks.reserve(npus_count);
    for (int i = 0; i < npus_count; i++) {
        all_ranks.push_back(i);
    }
    HTSimNetworkApi::reset_completion_tracker(all_ranks);
    for (int i = 0; i < npus_count; i++) {
        systems[i]->workload->fire();
    }

    // Run one scheduler/backend round at a time.  HTSim stops its current
    // eventlist when all ranks active in that round finish; the Python
    // controller then either assigns the next .et workload, asks the rank to
    // pass until a future arrival, or shuts the simulation down.
    std::vector<long long> pass_generation(npus_count, -1);
    std::vector<long long> pass_deadline(npus_count, 0);
    std::vector<long long> last_reported_iteration(npus_count, -1);
    long long state_generation = 0;
    bool exit = false;

    auto askable = [&](int rank) {
        if (pass_generation[rank] < 0) {
            return true;
        }
        if (pass_generation[rank] != state_generation) {
            return true;
        }
        return pass_deadline[rank] > 0 &&
               static_cast<long long>(ht.get_time_ns()) >= pass_deadline[rank];
    };

    while (!exit) {
        while (ht.do_next_event()) {
        }

        std::vector<int> active_next_round;
        long long next_deadline = 0;
        bool assigned_workload = false;
        bool reported = false;

        for (int i = 0; i < npus_count; i++) {
            auto* workload = systems[i]->workload;
            if (workload->is_sleep || !workload->is_finished || !askable(i)) {
                if (pass_deadline[i] > 0 &&
                    (next_deadline == 0 || pass_deadline[i] < next_deadline)) {
                    next_deadline = pass_deadline[i];
                }
                continue;
            }

            reported = true;
            // A completion report is a scheduler-visible state change when
            // this rank advances to a new ASTRA workload iteration.  This is
            // what re-opens ranks that answered "pass" earlier in the same
            // round: for example, TP rank 0 may finish before rank 1, and
            // only rank 1's later report lets rank 0 build the next batch.
            if (last_reported_iteration[i] !=
                static_cast<long long>(workload->iteration)) {
                last_reported_iteration[i] = workload->iteration;
                ++state_generation;
            }
            workload->report();
            const auto cycle = AstraSim::Sys::boostedTick();
            const auto communication_cycle =
                cycle - workload->hw_resource->tics_gpu_ops;
            const bool compact_logs = std::getenv("LLMSERVINGSIM_COMPACT_LOGS") != nullptr;
            if (compact_logs) {
                // HTSim/ASTRA diagnostics can emit a progress character without
                // a trailing newline while the final event callback is running.
                // Force the protocol marker onto a fresh line so Controller's
                // compact parser cannot lose rank 0's first report.
                std::cout << "\nR " << systems[i]->id << " "
                          << workload->iteration << " " << cycle << " "
                          << communication_cycle << std::endl;
            } else {
                std::cout << "sys[" << systems[i]->id << "] iteration "
                          << workload->iteration << " finished, " << cycle
                          << " cycles, exposed communication "
                          << communication_cycle << " cycles." << std::endl;
            }
            std::cout << "Waiting" << std::endl;

            std::string command;
            if (!std::getline(std::cin, command)) {
                exit = true;
                break;
            }
            if (command.rfind("pass", 0) == 0) {
                const long long deadline = command.size() > 5
                    ? std::strtoll(command.c_str() + 5, nullptr, 10) : 0;
                if (deadline < 0) {
                    ++state_generation;
                    pass_generation[i] = state_generation;
                    pass_deadline[i] = 0;
                } else {
                    pass_generation[i] = state_generation;
                    pass_deadline[i] = deadline;
                    if (deadline > 0 &&
                        (next_deadline == 0 || deadline < next_deadline)) {
                        next_deadline = deadline;
                    }
                }
                continue;
            }

            ++state_generation;
            std::fill(pass_generation.begin(), pass_generation.end(), -1);
            std::fill(pass_deadline.begin(), pass_deadline.end(), 0);
            if (command == "done") {
                workload->is_sleep = true;
                continue;
            }
            if (command == "exit") {
                exit = true;
                break;
            }

            // A DP/EP collective must be installed on every participant
            // before any participant is allowed to execute it.  The Python
            // frontend sends one atomic command rather than relying on a
            // sequence of independent stdin replies, which could start the
            // first rank while the remaining ranks were still in pass state.
            if (command.rfind("group ", 0) == 0) {
                const auto first_space = command.find(' ', 6);
                if (first_space == std::string::npos || first_space + 1 >= command.size()) {
                    std::cerr << "Malformed HTSim group command: " << command << std::endl;
                    exit = true;
                    break;
                }
                const auto workload_path = command.substr(6, first_space - 6);
                const auto rank_list = command.substr(first_space + 1);
                std::vector<int> group_ranks;
                std::size_t begin = 0;
                while (begin < rank_list.size()) {
                    const auto comma = rank_list.find(',', begin);
                    const auto token = rank_list.substr(
                        begin, comma == std::string::npos ? std::string::npos : comma - begin);
                    if (token.empty()) {
                        std::cerr << "Malformed HTSim group rank list: " << command << std::endl;
                        exit = true;
                        break;
                    }
                    const int rank = std::stoi(token);
                    if (rank < 0 || rank >= npus_count) {
                        std::cerr << "HTSim group rank out of range: " << rank << std::endl;
                        exit = true;
                        break;
                    }
                    group_ranks.push_back(rank);
                    if (comma == std::string::npos) {
                        begin = rank_list.size();
                    } else {
                        begin = comma + 1;
                    }
                }
                if (exit || group_ranks.empty()) {
                    break;
                }
                ht.set_endtime_infinite();
                for (const int rank : group_ranks) {
                    systems[rank]->workload->add_workload(workload_path, {});
                    active_next_round.push_back(rank);
                }
                assigned_workload = true;
                continue;
            }

            // stop_simulation() set the eventlist end time to the current
            // timestamp when the prior round completed.  Re-open it before
            // adding a graph for the next serving round.
            ht.set_endtime_infinite();
            workload->add_workload(command, {});
            active_next_round.push_back(i);
            assigned_workload = true;
        }

        if (exit) {
            break;
        }

        if (assigned_workload) {
            HTSimNetworkApi::reset_completion_tracker(active_next_round);
            continue;
        }

        if (next_deadline > static_cast<long long>(ht.get_time_ns())) {
            // Keep the event loop alive until the next open-loop arrival.
            // No network traffic is fabricated; this is only a scheduler wakeup.
            ht.set_endtime_infinite();
            HTSimNetworkApi::reset_completion_tracker({});
            const auto delta = static_cast<long double>(
                next_deadline - static_cast<long long>(ht.get_time_ns()));
            ht.schedule_astra_event(delta, htsim_idle_wakeup, nullptr);
            continue;
        }

        if (!reported) {
            std::cerr << "HTSim interactive frontend has no active workload "
                      << "or future scheduler wakeup." << std::endl;
            break;
        }

        // A pass -1 state change can make a rank askable again without a
        // network event.  Let the controller resolve that state, but avoid a
        // tight loop if all ranks remain idle.
        ht.set_endtime_infinite();
        HTSimNetworkApi::reset_completion_tracker({});
        ht.schedule_astra_event(1, htsim_idle_wakeup, nullptr);
    }

    // terminate simulation
    std::cout << "Checking Non-Exited Systems ..." << std::endl;
    std::cout << "All Request Has Been Exited" << std::endl;
    AstraSim::LoggerFactory::shutdown();

    ht.finish();
    return 0;
}
