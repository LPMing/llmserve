#define KVEP_REPLAY_SKIP_GLOBAL_ROUTING 1
#include "astra-sim/common/AstraNetworkAPI.hh"
#include "astra-sim/system/Sys.hh"
#include "extern/memory_backend/analytical/AnalyticalMemory.hh"
#include "entry.h"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <unordered_set>
#include <sstream>
#include <string>
#include <vector>

using namespace ns3;
using namespace std;

namespace {

enum class TrafficMask { FULL, KV_ONLY, EP_ONLY };
TrafficMask traffic_mask = TrafficMask::FULL;
bool persistent_ep_qps = false;
bool stable_ep_qp_ports = false;
unordered_set<uint64_t> excluded_kv_request_ids;
uint64_t issued_events = 0;
uint64_t suppressed_events = 0;
uint64_t excluded_kv_events = 0;
uint64_t local_ep_events = 0;

struct ReplayEvent {
  uint64_t start_ns = 0;
  uint32_t src = 0;
  uint32_t dst = 0;
  uint64_t bytes = 0;
  uint32_t event_type = AstraSim::NETWORK_EVENT_UNKNOWN;
  uint64_t request_id = AstraSim::NO_REQUEST_ID;
  uint64_t collective_id = 0;
  uint32_t layer_id = 0;
  uint32_t tag = 0;
  string active_request_ids;
  string serving_role;
};

static uint64_t parse_u64(const string& value, uint64_t fallback = 0) {
  if (value.empty() || value == "-1") return fallback;
  return stoull(value);
}

static uint32_t parse_u32(const string& value, uint32_t fallback = 0) {
  if (value.empty() || value == "-1") return fallback;
  return static_cast<uint32_t>(stoul(value));
}

static string clean_csv_field(string value) {
  value.erase(remove_if(value.begin(), value.end(), [](unsigned char ch) {
    return ch == '\r' || ch == '\n';
  }), value.end());
  replace(value.begin(), value.end(), ',', ';');
  return value;
}

static vector<string> split_csv_row(const string& line) {
  vector<string> fields;
  stringstream stream(line);
  string field;
  while (getline(stream, field, ',')) fields.push_back(field);
  return fields;
}

static bool load_rank_to_nic_map(const string& path) {
  if (path.empty()) return true;
  ifstream input(path);
  if (!input.is_open()) {
    cerr << "cannot open rank-to-NIC map: " << path << "\n";
    return false;
  }
  string line;
  if (!getline(input, line)) return false;
  vector<string> header = split_csv_row(line);
  auto find_column = [&](const string& name) -> int {
    auto found = find(header.begin(), header.end(), name);
    return found == header.end() ? -1 : static_cast<int>(found - header.begin());
  };
  const int rank_col = find_column("astra_rank");
  const int server_col = find_column("server_id");
  const int nic_col = find_column("nic_id");
  if (rank_col < 0 || server_col < 0 || nic_col < 0) {
    cerr << "rank-to-NIC map needs astra_rank,server_id,nic_id columns\n";
    return false;
  }
  while (getline(input, line)) {
    if (line.empty()) continue;
    vector<string> fields = split_csv_row(line);
    const size_t required = static_cast<size_t>(max(rank_col, max(server_col, nic_col)));
    if (fields.size() <= required) continue;
    ReplayRankEndpoint endpoint;
    endpoint.nic_node = static_cast<uint32_t>(stoul(fields[nic_col]));
    endpoint.server_id = fields[server_col];
    replay_rank_to_nic[static_cast<uint32_t>(stoul(fields[rank_col]))] = endpoint;
  }
  return !replay_rank_to_nic.empty();
}

static bool read_event_line(const string& line, ReplayEvent* event) {
  if (line.empty() || line[0] == '#') return false;
  stringstream stream(line);
  vector<string> fields;
  string field;
  while (getline(stream, field, ',')) fields.push_back(field);
  if (fields.size() < 9 || fields[0] == "start_ns") return false;
  event->start_ns = parse_u64(fields[0]);
  event->src = parse_u32(fields[1]);
  event->dst = parse_u32(fields[2]);
  event->bytes = parse_u64(fields[3]);
  event->event_type = parse_u32(fields[4]);
  event->request_id = parse_u64(fields[5], AstraSim::NO_REQUEST_ID);
  event->collective_id = parse_u64(fields[6]);
  event->layer_id = parse_u32(fields[7]);
  event->tag = parse_u32(fields[8]);
  if (fields.size() > 9) event->active_request_ids = clean_csv_field(fields[9]);
  if (fields.size() > 10) event->serving_role = clean_csv_field(fields[10]);
  return event->bytes > 0;
}

static vector<ReplayEvent> read_events(const string& path) {
  ifstream input(path);
  if (!input.is_open()) throw runtime_error("cannot open replay file: " + path);
  vector<ReplayEvent> events;
  string line;
  while (getline(input, line)) {
    ReplayEvent event;
    if (read_event_line(line, &event)) events.push_back(event);
  }
  stable_sort(events.begin(), events.end(),
              [](const ReplayEvent& left, const ReplayEvent& right) {
                return left.start_ns < right.start_ns;
              });
  return events;
}

static void noop_message_handler(void*) {}

static void issue_event(ReplayEvent event) {
  const bool is_kv = event.event_type == AstraSim::NETWORK_EVENT_P2D_KV;
  const bool is_ep =
      event.event_type == AstraSim::NETWORK_EVENT_EP_DISPATCH ||
      event.event_type == AstraSim::NETWORK_EVENT_EP_COMBINE;
  const bool enabled =
      traffic_mask == TrafficMask::FULL ||
      (traffic_mask == TrafficMask::KV_ONLY && is_kv) ||
      (traffic_mask == TrafficMask::EP_ONLY && is_ep);
  const bool excluded_kv =
      is_kv && excluded_kv_request_ids.count(event.request_id) != 0;
  if (!enabled || excluded_kv) {
    // Preserve the source-port sequence used by the full replay. The source
    // port participates in ECMP hashing, so simply deleting the other traffic
    // class would silently change the retained flows' physical paths.
    // Port-number progression is associated with the GPU-rank endpoints.
    // Shared NIC nodes are intermediate switches, not RDMA application hosts.
    ++portNumber[event.src][event.dst];
    ++suppressed_events;
    if (excluded_kv) ++excluded_kv_events;
    return;
  }
  if (is_ep && !replay_rank_to_nic.empty()) {
    auto src = replay_rank_to_nic.find(event.src);
    auto dst = replay_rank_to_nic.find(event.dst);
    if (src == replay_rank_to_nic.end() || dst == replay_rank_to_nic.end()) {
      cerr << "EP replay rank missing from rank-to-NIC map: " << event.src
           << " -> " << event.dst << "\n";
      return;
    }
    if (src->second.server_id == dst->second.server_id) {
      // Intra-server EP is NVSwitch-local and is intentionally excluded from
      // this scale-out packet replay.
      ++local_ep_events;
      return;
    }
  }
  if (event.bytes > static_cast<uint64_t>(INT32_MAX)) {
    cerr << "Replay event exceeds ns-3 send_flow integer limit: "
         << event.bytes << " bytes\n";
    return;
  }
  AstraSim::sim_request request;
  request.srcRank = event.src;
  request.dstRank = event.dst;
  request.tag = event.tag;
  request.reqCount = event.bytes;
  request.layerNum = event.layer_id;
  request.requestId = event.request_id;
  request.collectiveId = event.collective_id;
  request.eventType = event.event_type;
  request.activeRequestIds = event.active_request_ids;
  request.servingRole = event.serving_role;
  send_flow(static_cast<int>(event.src), static_cast<int>(event.dst),
            static_cast<int>(event.bytes), &noop_message_handler, nullptr,
            static_cast<int>(event.tag), &request);
  ++issued_events;
}

static string value_after_equals(const string& arg, const string& key) {
  const string prefix = "--" + key + "=";
  if (arg.rfind(prefix, 0) != 0) return "";
  return arg.substr(prefix.size());
}

}  // namespace

int main(int argc, char** argv) {
  string network_configuration;
  string replay_file;
  string rank_to_nic_map_path;
  uint64_t stop_guard_ns = 5'000'000'000ULL;
  for (int index = 1; index < argc; ++index) {
    string arg(argv[index]);
    string value;
    if (!(value = value_after_equals(arg, "network-configuration")).empty()) {
      network_configuration = value;
    } else if (!(value = value_after_equals(arg, "replay-file")).empty()) {
      replay_file = value;
    } else if (!(value = value_after_equals(arg, "rank-to-nic-map")).empty()) {
      rank_to_nic_map_path = value;
    } else if (!(value = value_after_equals(arg, "stop-guard-ns")).empty()) {
      stop_guard_ns = parse_u64(value, stop_guard_ns);
    } else if (!(value = value_after_equals(arg, "traffic-class")).empty()) {
      if (value == "FULL") {
        traffic_mask = TrafficMask::FULL;
      } else if (value == "KV_ONLY") {
        traffic_mask = TrafficMask::KV_ONLY;
      } else if (value == "EP_ONLY") {
        traffic_mask = TrafficMask::EP_ONLY;
      } else {
        cerr << "invalid --traffic-class=" << value
             << " (expected FULL, KV_ONLY, or EP_ONLY)\n";
        return 2;
      }
    } else if (!(value = value_after_equals(arg, "exclude-kv-request-id")).empty()) {
      try {
        excluded_kv_request_ids.insert(parse_u64(value, UINT64_MAX));
      } catch (const exception& error) {
        cerr << "invalid --exclude-kv-request-id=" << value << ": "
             << error.what() << "\n";
        return 2;
      }
    } else if (!(value = value_after_equals(arg, "persistent-ep-qps")).empty()) {
      if (value == "1" || value == "true" || value == "TRUE") {
        persistent_ep_qps = true;
      } else if (value == "0" || value == "false" || value == "FALSE") {
        persistent_ep_qps = false;
      } else {
        cerr << "invalid --persistent-ep-qps=" << value
             << " (expected 0 or 1)\n";
        return 2;
      }
    } else if (!(value = value_after_equals(arg, "stable-ep-ports")).empty()) {
      if (value == "1" || value == "true" || value == "TRUE") {
        stable_ep_qp_ports = true;
      } else if (value == "0" || value == "false" || value == "FALSE") {
        stable_ep_qp_ports = false;
      } else {
        cerr << "invalid --stable-ep-ports=" << value
             << " (expected 0 or 1)\n";
        return 2;
      }
    }
  }
  persistent_ep_qps_enabled = persistent_ep_qps;
  stable_ep_qp_ports_enabled = stable_ep_qp_ports;
  if (network_configuration.empty() || replay_file.empty()) {
    cerr << "usage: KVEPReplay --network-configuration=FILE "
            "--replay-file=CSV [--stop-guard-ns=NS] "
            "[--traffic-class=FULL|KV_ONLY|EP_ONLY] "
            "[--exclude-kv-request-id=ID ...] "
            "[--rank-to-nic-map=CSV] "
            "[--persistent-ep-qps=0|1] [--stable-ep-ports=0|1]\n";
    return 2;
  }

  vector<ReplayEvent> events;
  try {
    events = read_events(replay_file);
  } catch (const exception& error) {
    cerr << error.what() << "\n";
    return 2;
  }
  if (events.empty()) {
    cerr << "replay file contains no data events: " << replay_file << "\n";
    return 2;
  }
  if (!load_rank_to_nic_map(rank_to_nic_map_path)) {
    cerr << "failed to load rank-to-NIC map: " << rank_to_nic_map_path << "\n";
    return 2;
  }

  if (setup_ns3_simulation(network_configuration) != 0) return 1;
  for (const ReplayEvent& event : events) {
    Simulator::Schedule(NanoSeconds(event.start_ns), &issue_event, event);
  }
  const uint64_t stop_ns = events.back().start_ns + stop_guard_ns;
  Simulator::Stop(NanoSeconds(stop_ns));
  Simulator::Run();
  Simulator::Destroy();
  cout << "KVEP replay completed: events=" << events.size()
       << " issued=" << issued_events
       << " suppressed=" << suppressed_events
       << " excluded_kv=" << excluded_kv_events
       << " local_ep=" << local_ep_events
       << " stop_ns=" << stop_ns << "\n";
  return 0;
}
