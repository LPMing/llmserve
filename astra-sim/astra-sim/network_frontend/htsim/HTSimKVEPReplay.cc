#include "HTSimSession.hh"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct ReplayEvent {
    uint64_t start_ns = 0;
    int src = 0;
    int dst = 0;
    uint64_t bytes = 0;
    int event_type = 0;
    int request_id = -1;
    int collective_id = -1;
    int layer_id = -1;
    int tag = 0;
    std::string active_request_ids;
    std::string serving_role;
};

struct FlowContext {
    ReplayEvent event;
    int flow_id = 0;
    uint64_t end_ns = 0;
    bool issued = false;
    bool completed = false;
};

static size_t expected_flows = 0;
static size_t completed_flows = 0;

static std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, ',')) {
        fields.push_back(field);
    }
    return fields;
}

static uint64_t parse_u64(const std::string& value, const char* name) {
    try {
        return std::stoull(value);
    } catch (...) {
        throw std::runtime_error(std::string("invalid ") + name + ": " + value);
    }
}

static int parse_int(const std::string& value, const char* name) {
    try {
        return std::stoi(value);
    } catch (...) {
        throw std::runtime_error(std::string("invalid ") + name + ": " + value);
    }
}

static std::vector<ReplayEvent> load_events(const std::string& path) {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("cannot open replay file: " + path);
    }

    std::vector<ReplayEvent> events;
    std::string line;
    std::getline(input, line);
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }
        auto fields = split_csv(line);
        if (fields.size() < 11) {
            throw std::runtime_error("replay row has fewer than 11 fields: " + line);
        }
        ReplayEvent event;
        event.start_ns = parse_u64(fields[0], "start_ns");
        event.src = parse_int(fields[1], "src");
        event.dst = parse_int(fields[2], "dst");
        event.bytes = parse_u64(fields[3], "bytes");
        event.event_type = parse_int(fields[4], "event_type");
        event.request_id = parse_int(fields[5], "request_id");
        event.collective_id = parse_int(fields[6], "collective_id");
        event.layer_id = parse_int(fields[7], "layer_id");
        event.tag = parse_int(fields[8], "tag");
        event.active_request_ids = fields[9];
        event.serving_role = fields[10];
        if (event.bytes > static_cast<uint64_t>(std::numeric_limits<int>::max())) {
            throw std::runtime_error("flow exceeds HTSim int-sized FlowInfo: " + fields[3]);
        }
        events.push_back(std::move(event));
    }
    std::stable_sort(events.begin(), events.end(),
                     [](const ReplayEvent& lhs, const ReplayEvent& rhs) {
                         return lhs.start_ns < rhs.start_ns;
                     });
    return events;
}

static void flow_finished(void* argument) {
    auto* context = static_cast<FlowContext*>(argument);
    if (context->completed) {
        return;
    }
    context->end_ns = static_cast<uint64_t>(HTSim::HTSimSession::instance().get_time_ns());
    context->completed = true;
    completed_flows++;
    if (expected_flows > 0 && completed_flows == expected_flows) {
        HTSim::HTSimSession::instance().stop_simulation();
    }
}

static void issue_flow(void* argument) {
    auto* context = static_cast<FlowContext*>(argument);
    if (context->issued) {
        return;
    }
    context->issued = true;
    HTSim::FlowInfo flow(context->event.src, context->event.dst,
                         context->event.bytes, context->event.tag);
    HTSim::HTSimSession::instance().send_flow(
        flow, context->flow_id, &flow_finished, context);
}

static void stop_replay(void*) {
    HTSim::HTSimSession::instance().stop_simulation();
}

struct Options {
    std::string replay_file;
    std::string topology_file;
    std::string output_file;
    int nodes = 512;
    int mtu = 4096;
    unsigned int seed = 1;
    uint64_t stop_guard_ns = 5'000'000'000ULL;
    uint64_t queue_sample_us = 100'000ULL;
};

static void usage(const char* program) {
    std::cerr << "Usage: " << program
              << " --replay-file FILE --htsim-topology FILE"
              << " [--output FILE] [--nodes N] [--mtu BYTES]"
              << " [--seed N] [--stop-guard-ns NS]" << std::endl;
}

static Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string key(argv[i]);
        auto next = [&](const char* name) -> std::string {
            if (i + 1 >= argc) {
                throw std::runtime_error(std::string("missing value for ") + name);
            }
            return argv[++i];
        };
        if (key == "--replay-file") {
            options.replay_file = next("--replay-file");
        } else if (key == "--htsim-topology") {
            options.topology_file = next("--htsim-topology");
        } else if (key == "--output") {
            options.output_file = next("--output");
        } else if (key == "--nodes") {
            options.nodes = parse_int(next("--nodes"), "nodes");
        } else if (key == "--mtu") {
            options.mtu = parse_int(next("--mtu"), "mtu");
        } else if (key == "--seed") {
            options.seed = static_cast<unsigned int>(parse_u64(next("--seed"), "seed"));
        } else if (key == "--stop-guard-ns") {
            options.stop_guard_ns = parse_u64(next("--stop-guard-ns"), "stop_guard_ns");
        } else if (key == "--queue-sample-us") {
            options.queue_sample_us = parse_u64(next("--queue-sample-us"), "queue_sample_us");
        } else {
            throw std::runtime_error("unknown option: " + key);
        }
    }
    if (options.replay_file.empty() || options.topology_file.empty()) {
        throw std::runtime_error("--replay-file and --htsim-topology are required");
    }
    if (options.output_file.empty()) {
        options.output_file = options.replay_file + ".htsim.csv";
    }
    if (options.nodes <= 0 || options.mtu <= 0 || options.stop_guard_ns == 0 ||
        options.queue_sample_us == 0) {
        throw std::runtime_error("nodes, mtu, stop_guard_ns, and queue_sample_us must be positive");
    }
    return options;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parse_options(argc, argv);
        const auto events = load_events(options.replay_file);
        std::vector<FlowContext> contexts;
        contexts.reserve(events.size());
        for (const auto& event : events) {
            contexts.push_back(FlowContext{event, static_cast<int>(contexts.size() + 1)});
        }
        expected_flows = contexts.size();
        uint64_t last_start_ns = 0;
        for (const auto& context : contexts) {
            last_start_ns = std::max(last_start_ns, context.event.start_ns);
        }

        HTSim::tm_info tm{options.nodes};
        std::vector<std::string> htsim_arguments = {
            "HTSimKVEPReplay", "-topo", options.topology_file,
            "-nodes", std::to_string(options.nodes), "-mtu",
            std::to_string(options.mtu), "-seed", std::to_string(options.seed),
            "-endtime-ns", std::to_string(last_start_ns + options.stop_guard_ns),
            "-queue-sample-us", std::to_string(options.queue_sample_us),
            "-o", options.output_file + ".htsim.log", "-path-output",
            options.output_file + ".paths.csv"};
        std::vector<char*> htsim_argv;
        htsim_argv.reserve(htsim_arguments.size());
        for (auto& argument : htsim_arguments) {
            htsim_argv.push_back(argument.data());
        }

        auto& session = HTSim::HTSimSession::init(
            &tm, static_cast<int>(htsim_argv.size()), htsim_argv.data(), HTSim::HTSimProto::Tcp);

        for (auto& context : contexts) {
            session.schedule_astra_event(
                static_cast<long double>(context.event.start_ns), &issue_flow, &context);
        }
        session.schedule_astra_event(
            static_cast<long double>(last_start_ns + options.stop_guard_ns),
            &stop_replay, nullptr);
        session.run(&tm);

        std::ofstream output(options.output_file);
        if (!output) {
            throw std::runtime_error("cannot open output file: " + options.output_file);
        }
        output << "flow_id,start_ns,end_ns,src,dst,bytes,event_type,request_id,"
                  "collective_id,layer_id,tag,active_request_ids,serving_role,completed\n";
        size_t completed = 0;
        for (const auto& context : contexts) {
            completed += context.completed ? 1 : 0;
            output << context.flow_id << ',' << context.event.start_ns << ','
                   << context.end_ns << ',' << context.event.src << ',' << context.event.dst
                   << ',' << context.event.bytes << ',' << context.event.event_type << ','
                   << context.event.request_id << ',' << context.event.collective_id << ','
                   << context.event.layer_id << ',' << context.event.tag << ','
                   << context.event.active_request_ids << ',' << context.event.serving_role
                   << ',' << (context.completed ? 1 : 0) << '\n';
        }
        std::cout << "HTSim replay completed flows " << completed << "/" << contexts.size()
                  << " mtu " << options.mtu << " bytes" << std::endl;
        session.finish();
        return completed == contexts.size() ? 0 : 2;
    } catch (const std::exception& error) {
        usage(argv[0]);
        std::cerr << "HTSimKVEPReplay error: " << error.what() << std::endl;
        return 1;
    }
}
