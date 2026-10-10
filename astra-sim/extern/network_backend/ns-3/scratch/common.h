/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation;
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 */

#undef PGO_TRAINING
#define PATH_TO_PGO_CONFIG "path_to_pgo_config"

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/error-model.h"
#include "ns3/global-route-manager.h"
#include "ns3/internet-module.h"
#include "ns3/ipv4-static-routing-helper.h"
#include "ns3/packet.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/qbb-helper.h"
#include <fstream>
#include <algorithm>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <queue>
#include <sstream>
#include <ns3/rdma-client-helper.h>
#include <ns3/rdma-client.h>
#include <ns3/rdma-driver.h>
#include <ns3/rdma.h>
#include <ns3/sim-setting.h>
#include <ns3/switch-node.h>
#include <time.h>
#include <unordered_map>

using namespace ns3;
using namespace std;

NS_LOG_COMPONENT_DEFINE("GENERIC_SIMULATION");

uint32_t cc_mode = 1;
bool enable_qcn = true, use_dynamic_pfc_threshold = true;
uint32_t packet_payload_size = 1000, l2_chunk_size = 0, l2_ack_interval = 0;
double pause_time = 5, simulator_stop_time = 3.01;
std::string topology_file, flow_file, trace_file, trace_output_file;
std::string fct_output_file = "fct.txt";
std::string pfc_output_file = "pfc.txt";
std::string comm_events_file;
std::string cc_telemetry_file;
std::string link_timeseries_file;
std::string link_summary_file;
std::string local_ecn_mark_file;
std::string kv_ep_network_policy = "FAIR";

double alpha_resume_interval = 55, rp_timer, ewma_gain = 1 / 16;
double rate_decrease_interval = 4;
uint32_t fast_recovery_times = 5;
std::string rate_ai, rate_hai, min_rate = "100Mb/s";
std::string dctcp_rate_ai = "1000Mb/s";

bool clamp_target_rate = false, l2_back_to_zero = false;
double error_rate_per_link = 0.0;
uint32_t has_win = 1;
uint32_t global_t = 1;
uint32_t mi_thresh = 5;
bool var_win = false, fast_react = true;
bool multi_rate = true;
bool sample_feedback = false;
double pint_log_base = 1.05;
double pint_prob = 1.0;
double u_target = 0.95;
uint32_t int_multi = 1;
bool rate_bound = true;
int nic_total_pause_time =
    0; // slightly less than finish time without inefficiency in us

uint32_t ack_high_prio = 0;
uint64_t link_down_time = 0;
uint32_t link_down_A = 0, link_down_B = 0;

uint32_t enable_trace = 1;

uint32_t buffer_size = 16;

uint32_t qlen_dump_interval = 1000, qlen_mon_interval = 100;
uint64_t qlen_mon_start = 0, qlen_mon_end = 2100000000;
string qlen_mon_file;

unordered_map<uint64_t, uint32_t> rate2kmax, rate2kmin;
unordered_map<uint64_t, double> rate2pmax;

/************************************************
 * Runtime varibles
 ***********************************************/
std::ifstream topof, flowf, tracef;

struct CommEventKey {
  uint32_t src;
  uint32_t dst;
  uint32_t port;

  bool operator<(const CommEventKey& other) const {
    if (src != other.src) return src < other.src;
    if (dst != other.dst) return dst < other.dst;
    return port < other.port;
  }
};

struct CommEventStart {
  uint64_t event_id;
  uint32_t src;
  uint32_t dst;
  uint32_t port;
  int tag;
  uint64_t bytes;
  uint64_t issue_ns;
  uint64_t start_ns;
  uint64_t request_id;
  uint64_t collective_id;
  uint32_t event_type;
  uint32_t layer_id;
  uint16_t priority_group;
  std::string active_request_ids;
  std::string serving_role;
  std::string path;
  std::string directed_link_ids;
  int64_t src_rank;
  int64_t dst_rank;
};

std::ofstream comm_events_stream;
std::ofstream cc_telemetry_stream;
std::ofstream local_ecn_mark_stream;
std::map<CommEventKey, std::map<int, CommEventStart>> comm_events_inflight;
// Actual physical directed links observed by forward UDP data packets.  The
// topology may contain parallel interfaces between the same node pair, so the
// static endpoint BFS path is not sufficient for per-flow attribution.
std::map<CommEventKey, std::vector<uint32_t>> comm_event_actual_link_ids;
uint64_t next_comm_event_id = 0;

struct LinkTelemetryState {
  uint32_t link_id;
  uint32_t src;
  uint32_t dst;
  uint64_t capacity_bps;
  Ptr<QbbNetDevice> device;
  uint64_t tx_bytes = 0;
  uint64_t tx_packets = 0;
  uint64_t queue_packets = 0;
  uint64_t ecn_marks = 0;
  uint64_t pfc_pause = 0;
  uint64_t drop_count = 0;
  uint64_t queue_max_bytes = 0;
  uint64_t last_time_ns = 0;
  uint64_t last_tx_time_ns = 0;
  uint64_t last_tx_bytes = 0;
  uint64_t last_tx_packet_bytes = 0;
  uint64_t last_timeseries_emit_ns = 0;
  long double queue_byte_ns = 0;
  double peak_utilization = 0.0;
};

std::vector<LinkTelemetryState> link_telemetry_states;
std::ofstream link_timeseries_stream;
std::ofstream link_summary_stream;
uint64_t link_telemetry_interval_ns = 0;
std::map<std::pair<uint32_t, uint32_t>, uint32_t> directed_link_ids;
std::map<uint32_t, std::vector<uint32_t>> topology_adjacency;

static std::string telemetry_request_id(uint64_t request_id);

static void telemetry_local_ecn_mark(uint32_t switch_id, uint32_t egress_port,
                                     uint32_t queue_index,
                                     Ptr<const Packet> packet,
                                     uint32_t queue_bytes,
                                     uint32_t kmin_bytes,
                                     uint32_t kmax_bytes) {
  if (!local_ecn_mark_stream.is_open() || packet == nullptr) return;
  CustomHeader header(CustomHeader::L2_Header | CustomHeader::L3_Header |
                      CustomHeader::L4_Header);
  if (packet->PeekHeader(header) == 0 || header.l3Prot != 0x11) return;

  uint32_t link_id = std::numeric_limits<uint32_t>::max();
  uint32_t next_node = std::numeric_limits<uint32_t>::max();
  for (const auto& state : link_telemetry_states) {
    if (state.src == switch_id && state.device != nullptr &&
        state.device->GetIfIndex() == egress_port) {
      link_id = state.link_id;
      next_node = state.dst;
      break;
    }
  }

  const uint32_t src = (header.sip >> 8) & 0xffff;
  const uint32_t dst = (header.dip >> 8) & 0xffff;
  const CommEventKey key{src, dst, header.udp.sport};
  std::string traffic_class = "UNMATCHED";
  std::string event_ids;
  std::string request_ids;
  std::string collective_ids;
  std::string layer_ids;
  auto active = comm_events_inflight.find(key);
  if (active != comm_events_inflight.end() && !active->second.empty()) {
    bool saw_kv = false;
    bool saw_ep = false;
    bool saw_other = false;
    for (const auto& tagged : active->second) {
      const CommEventStart& event = tagged.second;
      if (!event_ids.empty()) {
        event_ids += ";";
        request_ids += ";";
        collective_ids += ";";
        layer_ids += ";";
      }
      event_ids += std::to_string(event.event_id);
      request_ids += telemetry_request_id(event.request_id);
      collective_ids += std::to_string(event.collective_id);
      layer_ids += std::to_string(event.layer_id);
      if (event.event_type == 1) saw_kv = true;
      else if (event.event_type == 2 || event.event_type == 3) saw_ep = true;
      else saw_other = true;
    }
    const unsigned classes = static_cast<unsigned>(saw_kv) +
                             static_cast<unsigned>(saw_ep) +
                             static_cast<unsigned>(saw_other);
    if (classes > 1) traffic_class = "AMBIGUOUS";
    else if (saw_kv) traffic_class = "KV_MOVEMENT";
    else if (saw_ep) traffic_class = "EP";
    else if (saw_other) traffic_class = "OTHER";
  }

  local_ecn_mark_stream << Simulator::Now().GetTimeStep() << ","
                        << switch_id << "," << link_id << "," << next_node
                        << "," << egress_port << "," << queue_index << ","
                        << queue_bytes << "," << kmin_bytes << ","
                        << kmax_bytes << "," << packet->GetUid() << ","
                        << static_cast<uint32_t>(header.GetIpv4EcnBits()) << ","
                        << header.sip << "," << header.dip << ","
                        << header.udp.sport << "," << header.udp.dport << ","
                        << header.udp.seq << "," << traffic_class << ","
                        << event_ids << "," << request_ids << ","
                        << collective_ids << "," << layer_ids << ","
                        << src << "-" << dst << "-" << header.udp.sport << "-"
                        << header.udp.dport
                        << "\n";
}

static std::string telemetry_request_id(uint64_t request_id) {
  if (request_id == static_cast<uint64_t>(-1)) return "-1";
  return std::to_string(request_id);
}

static std::string path_for_endpoints(uint32_t src, uint32_t dst) {
  if (src == dst) return std::to_string(src);
  std::map<uint32_t, uint32_t> parent;
  std::queue<uint32_t> pending;
  parent[src] = src;
  pending.push(src);
  while (!pending.empty()) {
    uint32_t current = pending.front();
    pending.pop();
    for (uint32_t next : topology_adjacency[current]) {
      if (parent.find(next) != parent.end()) continue;
      parent[next] = current;
      pending.push(next);
      if (next == dst) break;
    }
  }
  if (parent.find(dst) == parent.end()) return "";
  std::vector<uint32_t> nodes;
  for (uint32_t current = dst;; current = parent[current]) {
    nodes.push_back(current);
    if (current == src) break;
  }
  std::reverse(nodes.begin(), nodes.end());
  std::ostringstream path;
  std::ostringstream links;
  for (size_t i = 0; i < nodes.size(); ++i) {
    if (i) path << "->";
    path << nodes[i];
    if (i + 1 < nodes.size()) {
      if (links.tellp() > 0) links << ";";
      auto it = directed_link_ids.find({nodes[i], nodes[i + 1]});
      links << (it == directed_link_ids.end() ? "-1" : std::to_string(it->second));
    }
  }
  return path.str() + "|" + links.str();
}

static void link_telemetry_sample(LinkTelemetryState* state, bool force = false) {
  if (!link_timeseries_stream.is_open()) return;
  uint64_t now = Simulator::Now().GetTimeStep();
  if (state->last_time_ns == 0) state->last_time_ns = now;
  if (now >= state->last_time_ns) {
    state->queue_byte_ns += static_cast<long double>(
        state->device->GetQueue()->GetNBytesTotal()) *
        static_cast<long double>(now - state->last_time_ns);
  }
  state->last_time_ns = now;
  uint64_t queue_bytes = state->device->GetQueue()->GetNBytesTotal();
  state->queue_max_bytes = std::max(state->queue_max_bytes, queue_bytes);
  if (!force && link_telemetry_interval_ns > 0 &&
      state->last_timeseries_emit_ns > 0 &&
      now < state->last_timeseries_emit_ns + link_telemetry_interval_ns) {
    return;
  }
  link_timeseries_stream << now << "," << state->link_id << ","
                         << state->src << "," << state->dst << ","
                         << state->capacity_bps << "," << state->tx_bytes << ","
                         << state->tx_packets << "," << queue_bytes << ","
                         << state->queue_packets << "," << state->ecn_marks << ","
                         << state->pfc_pause << "," << state->drop_count << "\n";
  state->last_timeseries_emit_ns = now;
}

static void telemetry_beq_enqueue(LinkTelemetryState* state,
                                  Ptr<const Packet> packet, uint32_t q_index) {
  state->queue_packets++;
  link_telemetry_sample(state);
}

static void telemetry_beq_dequeue(LinkTelemetryState* state,
                                  Ptr<const Packet> packet, uint32_t q_index) {
  if (state->queue_packets > 0) state->queue_packets--;
  link_telemetry_sample(state);
}

// Record the physical link selected by the packet-level ECMP hash.  This
// callback runs at physical transmission start, after switching has selected
// the outgoing interface.  Only forward UDP data packets are associated with a
// replay QP; ACK/CNP/PFC packets must not change the data-flow path.
static void record_actual_data_link(LinkTelemetryState* state,
                                    Ptr<const Packet> packet) {
  if (state == nullptr || packet == nullptr) return;
  CustomHeader header(CustomHeader::L2_Header | CustomHeader::L3_Header |
                      CustomHeader::L4_Header);
  if (packet->PeekHeader(header) == 0 || header.l3Prot != 0x11) return;
  CommEventKey key{
      (header.sip >> 8) & 0xffff,
      (header.dip >> 8) & 0xffff,
      header.udp.sport};
  auto event = comm_events_inflight.find(key);
  if (event == comm_events_inflight.end()) return;
  auto& links = comm_event_actual_link_ids[key];
  if (std::find(links.begin(), links.end(), state->link_id) == links.end()) {
    links.push_back(state->link_id);
  }
}

// QbbDequeue is a scheduler callback: multiple packets can be selected in one
// simulation tick before the device starts serializing them. Count TX only at
// the inherited PointToPointNetDevice physical-start trace, which represents
// the packet actually entering the configured-rate channel.
static void telemetry_phy_tx_begin(LinkTelemetryState* state,
                                   Ptr<const Packet> packet) {
  record_actual_data_link(state, packet);
  state->tx_bytes += packet->GetSize();
  state->tx_packets++;
  CustomHeader header(CustomHeader::L2_Header | CustomHeader::L3_Header |
                      CustomHeader::L4_Header);
  if (packet->PeekHeader(header) > 0 && header.GetIpv4EcnBits() == 3) {
    state->ecn_marks++;
  }
  uint64_t now = Simulator::Now().GetTimeStep();
  if (state->last_tx_time_ns != 0 && now > state->last_tx_time_ns &&
      state->last_tx_packet_bytes > 0 && state->capacity_bps > 0) {
    // The interval ends at this packet's physical start, so its occupied wire
    // time belongs to the preceding packet, not the just-started one.
    double interval_util =
        static_cast<double>(state->last_tx_packet_bytes) * 8.0e9 /
        (static_cast<double>(state->capacity_bps) *
         static_cast<double>(now - state->last_tx_time_ns));
    // Nanosecond timestamps quantize a 200-Gbps 84-byte packet to 3 ns rather
    // than 3.36 ns. Bound the physically meaningful utilization at one instead
    // of reporting a rounding artifact above line rate.
    state->peak_utilization = std::max(
        state->peak_utilization, std::min(1.0, interval_util));
  }
  state->last_tx_time_ns = now;
  state->last_tx_bytes = state->tx_bytes;
  state->last_tx_packet_bytes = packet->GetSize();
  link_telemetry_sample(state);
}

static void telemetry_qbb_drop(LinkTelemetryState* state,
                               Ptr<const Packet> packet, uint32_t q_index) {
  state->drop_count++;
  link_telemetry_sample(state);
}

static void telemetry_pfc(LinkTelemetryState* state, uint32_t type) {
  if (type == 1) state->pfc_pause++;
  link_telemetry_sample(state);
}

static void finalize_link_telemetry() {
  uint64_t end_ns = Simulator::Now().GetTimeStep();
  if (end_ns == 0) {
    for (const auto& state : link_telemetry_states)
      end_ns = std::max(end_ns, state.last_time_ns);
  }
  if (link_timeseries_stream.is_open()) {
    for (auto& state : link_telemetry_states)
      link_telemetry_sample(&state, true);
  }
  if (cc_telemetry_stream.is_open()) cc_telemetry_stream.flush();
  if (local_ecn_mark_stream.is_open()) local_ecn_mark_stream.flush();
  if (!link_summary_stream.is_open()) return;
  link_summary_stream << std::setprecision(12);
  for (const auto& state : link_telemetry_states) {
    double duration = static_cast<double>(std::max<uint64_t>(end_ns, 1));
    double mean_util = static_cast<double>(state.tx_bytes) * 8.0e9 /
                       (static_cast<double>(state.capacity_bps) * duration);
    double mean_queue = static_cast<double>(state.queue_byte_ns) /
                        static_cast<double>(std::max<uint64_t>(end_ns, 1));
    link_summary_stream << state.link_id << "," << state.src << ","
                        << state.dst << "," << state.capacity_bps << ","
                        << state.tx_bytes << "," << state.tx_packets << ","
                        << end_ns << "," << mean_util << ","
                        << state.peak_utilization << ","
                        << state.queue_max_bytes << "," << mean_queue << ","
                        << state.ecn_marks << "," << state.pfc_pause << ","
                        << state.drop_count << "\n";
  }
  link_summary_stream.flush();
}

static void telemetry_cnp(uint32_t node_id, Ptr<RdmaQueuePair> qp,
                           uint8_t ecnbits, uint16_t qfb, uint16_t total) {
  if (!cc_telemetry_stream.is_open() || qp == nullptr) return;
  cc_telemetry_stream << Simulator::Now().GetTimeStep() << ",CNP," << node_id
                      << "," << qp->sip.Get() << "," << qp->dip.Get()
                      << "," << qp->sport << "," << qp->dport << ","
                      << qp->m_pg << "," << qp->GetInitialSize() << ","
                      << qp->m_rate.GetBitRate() << ","
                      << qp->m_rate.GetBitRate() << ","
                      << qp->mlx.m_targetRate.GetBitRate() << ",0,"
                      << static_cast<uint32_t>(ecnbits) << "," << qfb << ","
                      << total << "," << qp->m_qpId << "," << qp->GetSrc()
                      << "," << qp->GetDest() << "\n";
}

static void telemetry_rate(uint32_t node_id, Ptr<RdmaQueuePair> qp,
                           uint64_t old_rate_bps, uint64_t new_rate_bps,
                           uint64_t target_rate_bps, uint8_t reason) {
  if (!cc_telemetry_stream.is_open() || qp == nullptr) return;
  cc_telemetry_stream << Simulator::Now().GetTimeStep() << ",RATE," << node_id
                      << "," << qp->sip.Get() << "," << qp->dip.Get()
                      << "," << qp->sport << "," << qp->dport << ","
                      << qp->m_pg << "," << qp->GetInitialSize() << ","
                      << old_rate_bps << "," << new_rate_bps << ","
                      << target_rate_bps << "," << static_cast<uint32_t>(reason)
                      << ",0,0,0," << qp->m_qpId << "," << qp->GetSrc()
                      << "," << qp->GetDest() << "\n";
}

static void telemetry_qp_message(uint32_t node_id, Ptr<RdmaQueuePair> qp,
                                 uint64_t message_bytes, uint8_t reused) {
  if (!cc_telemetry_stream.is_open() || qp == nullptr) return;
  const uint64_t rate = qp->m_rate.GetBitRate();
  cc_telemetry_stream << Simulator::Now().GetTimeStep() << ",QP_START," << node_id
                      << "," << qp->sip.Get() << "," << qp->dip.Get()
                      << "," << qp->sport << "," << qp->dport << ","
                      << qp->m_pg << "," << message_bytes << "," << rate
                      << "," << rate << "," << qp->mlx.m_targetRate.GetBitRate()
                      << "," << static_cast<uint32_t>(reused) << ",0,0,0,"
                      << qp->m_qpId << "," << qp->GetSrc() << ","
                      << qp->GetDest() << "\n";
}

static void record_comm_start(uint32_t src, uint32_t dst, uint32_t port,
                       int tag, uint64_t bytes,
                       uint64_t request_id = static_cast<uint64_t>(-1),
                       uint64_t collective_id = 0, uint32_t event_type = 0,
                       uint32_t layer_id = 0, uint16_t priority_group = 3,
                       const std::string& active_request_ids = "",
                       const std::string& serving_role = "",
                       int64_t src_rank = -1, int64_t dst_rank = -1) {
  if (!comm_events_stream.is_open()) return;
  uint64_t now = Simulator::Now().GetTimeStep();
  std::string path_info = path_for_endpoints(src, dst);
  size_t separator = path_info.find('|');
  std::string path = separator == std::string::npos
                         ? path_info
                         : path_info.substr(0, separator);
  std::string links = separator == std::string::npos
                          ? ""
                          : path_info.substr(separator + 1);
  CommEventStart event{next_comm_event_id++, src, dst, port, tag, bytes,
                       now, now, request_id, collective_id, event_type,
                       layer_id, priority_group, active_request_ids, serving_role,
                       path, links, src_rank, dst_rank};
  CommEventKey key{src, dst, port};
  comm_events_inflight[key][tag] = event;
  comm_event_actual_link_ids.try_emplace(key);
  comm_events_stream << "START," << event.event_id << ","
                     << telemetry_request_id(request_id)
                     << "," << collective_id << "," << event_type << ","
                     << layer_id << "," << active_request_ids << ","
                     << serving_role << ","
                     << src << "," << dst << ","
                     << port << "," << tag << "," << bytes << ","
                     << priority_group << ","
                     << event.issue_ns << "," << event.start_ns << ",-1,-1,"
                     << path << "," << links << "," << src_rank << ","
                     << dst_rank << "\n";
  comm_events_stream.flush();
}

void record_comm_api(const char* phase, uint32_t src, uint32_t dst,
                     int tag, uint64_t bytes,
                     uint64_t request_id = static_cast<uint64_t>(-1),
                     uint64_t collective_id = 0, uint32_t event_type = 0,
                     uint32_t layer_id = 0, uint16_t priority_group = 3,
                     const std::string& active_request_ids = "",
                     const std::string& serving_role = "",
                     int64_t src_rank = -1, int64_t dst_rank = -1) {
  if (!comm_events_stream.is_open()) return;
  comm_events_stream << phase << ",-1,"
                     << telemetry_request_id(request_id) << ","
                     << collective_id << "," << event_type << ","
                     << layer_id << "," << active_request_ids << ","
                     << serving_role << ","
                     << src << "," << dst
                     << ",-1," << tag << "," << bytes << ","
                     << priority_group << ","
                     << Simulator::Now().GetTimeStep()
                     << ",-1,-1,-1,,," << src_rank << "," << dst_rank << "\n";
  comm_events_stream.flush();
}

void record_comm_finish(uint32_t src, uint32_t dst, uint32_t port,
                        int tag, uint64_t bytes) {
  if (!comm_events_stream.is_open()) return;
  const CommEventKey qp_key{src, dst, port};
  auto qp_it = comm_events_inflight.find(qp_key);
  if (qp_it == comm_events_inflight.end()) return;
  auto it = qp_it->second.find(tag);
  if (it == qp_it->second.end()) return;
  const CommEventStart event = it->second;
  const uint64_t start_ns = event.start_ns;
  uint64_t end_ns = Simulator::Now().GetTimeStep();
  std::string actual_links = event.directed_link_ids;
  auto actual_it = comm_event_actual_link_ids.find(qp_key);
  if (actual_it != comm_event_actual_link_ids.end() &&
      !actual_it->second.empty()) {
    std::ostringstream observed;
    for (size_t index = 0; index < actual_it->second.size(); ++index) {
      if (index > 0) observed << ";";
      observed << actual_it->second[index];
    }
    actual_links = observed.str();
  }
  comm_events_stream << "END," << event.event_id << ","
                     << telemetry_request_id(event.request_id)
                     << "," << event.collective_id << ","
                     << event.event_type << "," << event.layer_id << ","
                     << event.active_request_ids << "," << event.serving_role
                     << "," << src << ","
                     << dst << "," << port << "," << tag
                     << "," << bytes << "," << event.priority_group << ","
                     << event.issue_ns << ","
                     << start_ns << "," << end_ns << ","
                     << (end_ns >= start_ns ? end_ns - start_ns : 0) << ","
                     << event.path << "," << actual_links << ","
                     << event.src_rank << "," << event.dst_rank << "\n";
  comm_events_stream.flush();
  qp_it->second.erase(it);
  if (qp_it->second.empty()) comm_events_inflight.erase(qp_it);
}

NodeContainer n;

uint64_t nic_rate;

uint64_t maxRtt, maxBdp;

std::vector<Ipv4Address> serverAddress;

// maintain port number for each host pair
std::unordered_map<uint32_t, unordered_map<uint32_t, uint16_t>> portNumber;

struct Interface {
  uint32_t idx;
  bool up;
  uint64_t delay;
  uint64_t bw;

  Interface() : idx(0), up(false) {}
};
map<Ptr<Node>, map<Ptr<Node>, Interface>> nbr2if;
// A topology may contain several physical interfaces between the same pair
// of nodes (for example the 16 leaf-spine links in S16).  ``nbr2if`` is kept
// as a representative link for distance/bandwidth calculations and legacy
// link-down helpers.  Routing must use this lossless parallel-interface map;
// otherwise repeated topology rows overwrite one another and all ECMP flows
// silently use only the last physical link.
map<Ptr<Node>, map<Ptr<Node>, vector<Interface>>> nbr2ifs;
// Mapping destination to next hop for each node: <node, <dest, <nexthop0, ...>
// > >
map<Ptr<Node>, map<Ptr<Node>, vector<Ptr<Node>>>> nextHop;
map<Ptr<Node>, map<Ptr<Node>, uint64_t>> pairDelay;
map<Ptr<Node>, map<Ptr<Node>, uint64_t>> pairTxDelay;
map<uint32_t, map<uint32_t, uint64_t>> pairBw;
map<Ptr<Node>, map<Ptr<Node>, uint64_t>> pairBdp;
map<uint32_t, map<uint32_t, uint64_t>> pairRtt;

struct FlowInput {
  uint32_t src, dst, pg, maxPacketCount, port, dport;
  double start_time;
  uint32_t idx;
};

FlowInput flow_input = {0};
uint32_t flow_num;
Ipv4Address node_id_to_ip(uint32_t id) {
  return Ipv4Address(0x0b000001 + ((id / 256) * 0x00010000) +
                     ((id % 256) * 0x00000100));
}

uint32_t ip_to_node_id(Ipv4Address ip) { return (ip.Get() >> 8) & 0xffff; }

void get_pfc(FILE *fout, Ptr<QbbNetDevice> dev, uint32_t type) {
  fprintf(fout, "%lu %u %u %u %u\n", Simulator::Now().GetTimeStep(),
          dev->GetNode()->GetId(), dev->GetNode()->GetNodeType(),
          dev->GetIfIndex(), type);
}

struct QlenDistribution {
  vector<uint32_t>
      cnt; // cnt[i] is the number of times that the queue len is i KB

  void add(uint32_t qlen) {
    uint32_t kb = qlen / 1000;
    if (cnt.size() < kb + 1)
      cnt.resize(kb + 1);
    cnt[kb]++;
  }
};
map<uint32_t, map<uint32_t, uint32_t>> queue_result;
void monitor_buffer(FILE *qlen_output, NodeContainer *n) {
  for (uint32_t i = 0; i < n->GetN(); i++) {
    if (n->Get(i)->GetNodeType() == 1) { // is switch
      Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n->Get(i));
      if (queue_result.find(i) == queue_result.end())
        queue_result[i];
      // fprintf(qlen_output, "\n");
      // fprintf(qlen_output, "time: %lu\n", Simulator::Now().GetTimeStep());
      int test = 0;
      for (uint32_t j = 1; j < sw->GetNDevices(); j++) {
        uint32_t size = 0;
        for (uint32_t k = 0; k < SwitchMmu::qCnt; k++)
          size += sw->m_mmu->egress_bytes[j][k];
        // if (queue_result[i].find(j) == queue_result[i].end())
        //{
        //	vector<uint32_t> v;
        //	queue_result[i][j] = v;
        // }
        if (size >= 1000) {
          queue_result[i][j] = size; // .push_back(size);
          if (test == 0) {
            test = 1;
            fprintf(qlen_output, "time %lu %u ", Simulator::Now().GetTimeStep(),
                    i);
          }
          // if(j==1){
          // fprintf(qlen_output, "t %lu %u j %u %u ",
          // Simulator::Now().GetTimeStep(), i, j, size);
          if (j < sw->GetNDevices() - 1) {
            test = 2;
            fprintf(qlen_output, "j %u %u ", j, size);
          } else if (j == sw->GetNDevices() - 1) {
            fprintf(qlen_output, "j %u %u\n", j, size);
            test = 3;
          }
        }
        if (j == sw->GetNDevices() - 1 && test == 2) {
          fprintf(qlen_output, "\n");
        }
        // else
        //	queue_result[i][j]+=size;
        // queue_result[i][j].add(size);
      }
      fflush(qlen_output);
      // fprintf(qlen_output, "\n");
    }
  }
  fflush(qlen_output);
  if (Simulator::Now().GetNanoSeconds() + qlen_mon_interval <= qlen_mon_end) {
    Simulator::Schedule(NanoSeconds(qlen_mon_interval), &monitor_buffer,
                        qlen_output, n);
  }
}

void CalculateRoute(Ptr<Node> host) {
  // queue for the BFS.
  vector<Ptr<Node>> q;
  // Distance from the host to each node.
  map<Ptr<Node>, int> dis;
  map<Ptr<Node>, uint64_t> delay;
  map<Ptr<Node>, uint64_t> txDelay;
  map<Ptr<Node>, uint64_t> bw;
  // init BFS.
  q.push_back(host);
  dis[host] = 0;
  delay[host] = 0;
  txDelay[host] = 0;
  bw[host] = 0xfffffffffffffffflu;
  // BFS.
  for (int i = 0; i < (int)q.size(); i++) {
    Ptr<Node> now = q[i];
    int d = dis[now];
    for (auto it = nbr2if[now].begin(); it != nbr2if[now].end(); it++) {
      // skip down link
      if (!it->second.up)
        continue;
      Ptr<Node> next = it->first;
      if (dis.find(next) == dis.end()) {
        dis[next] = d + 1;
        delay[next] = delay[now] + it->second.delay;
        txDelay[next] = txDelay[now] +
                        packet_payload_size * 1000000000lu * 8 / it->second.bw;
        bw[next] = std::min(bw[now], it->second.bw);
        if (next->GetNodeType() == 1)
          q.push_back(next);
      }
      if (d + 1 == dis[next]) {
        nextHop[next][host].push_back(now);
      }
    }
  }
  for (auto it : delay) {
    // std::cout << "pairDelay first "<< it.first->GetId() << " host " <<
    // host->GetId() << " delay " << it.second << std::endl;
    pairDelay[it.first][host] = it.second;
  }
  for (auto it : txDelay)
    pairTxDelay[it.first][host] = it.second;
  for (auto it : bw) {
    // std::cout << "pairBw first "<< it.first->GetId() << " host " <<
    // host->GetId() << " bw " << it.second << std::endl;
    pairBw[it.first->GetId()][host->GetId()] = it.second;
  }
}

void CalculateRoutes(NodeContainer &n) {
  for (int i = 0; i < (int)n.GetN(); i++) {
    Ptr<Node> node = n.Get(i);
    if (node->GetNodeType() == 0)
      CalculateRoute(node);
  }
}

void SetRoutingEntries() {
  for (auto i = nextHop.begin(); i != nextHop.end(); i++) {
    Ptr<Node> node = i->first;
    auto &table = i->second;
    for (auto j = table.begin(); j != table.end(); j++) {
      Ptr<Node> dst = j->first;
      Ipv4Address dstAddr = serverAddress[dst->GetId()];
      vector<Ptr<Node>> nexts = j->second;
      for (int k = 0; k < (int)nexts.size(); k++) {
        Ptr<Node> next = nexts[k];
        auto parallel_it = nbr2ifs[node].find(next);
        if (parallel_it == nbr2ifs[node].end()) {
          uint32_t interface = nbr2if[node][next].idx;
          if (node->GetNodeType() == 1)
            DynamicCast<SwitchNode>(node)->AddTableEntry(dstAddr, interface);
          else
            node->GetObject<RdmaDriver>()->m_rdma->AddTableEntry(
                dstAddr, interface);
          continue;
        }
        for (const Interface& link : parallel_it->second) {
          if (!link.up) continue;
          if (node->GetNodeType() == 1)
            DynamicCast<SwitchNode>(node)->AddTableEntry(dstAddr, link.idx);
          else
            node->GetObject<RdmaDriver>()->m_rdma->AddTableEntry(
                dstAddr, link.idx);
        }
      }
    }
  }
}

// take down the link between a and b, and redo the routing
void TakeDownLink(NodeContainer n, Ptr<Node> a, Ptr<Node> b) {
  if (!nbr2if[a][b].up)
    return;
  // take down link between a and b
  nbr2if[a][b].up = nbr2if[b][a].up = false;
  nextHop.clear();
  CalculateRoutes(n);
  // clear routing tables
  for (uint32_t i = 0; i < n.GetN(); i++) {
    if (n.Get(i)->GetNodeType() == 1)
      DynamicCast<SwitchNode>(n.Get(i))->ClearTable();
    else
      n.Get(i)->GetObject<RdmaDriver>()->m_rdma->ClearTable();
  }
  DynamicCast<QbbNetDevice>(a->GetDevice(nbr2if[a][b].idx))->TakeDown();
  DynamicCast<QbbNetDevice>(b->GetDevice(nbr2if[b][a].idx))->TakeDown();
  // reset routing table
  SetRoutingEntries();

  // redistribute qp on each host
  for (uint32_t i = 0; i < n.GetN(); i++) {
    if (n.Get(i)->GetNodeType() == 0)
      n.Get(i)->GetObject<RdmaDriver>()->m_rdma->RedistributeQp();
  }
}

uint64_t get_nic_rate(NodeContainer &n) {
  for (uint32_t i = 0; i < n.GetN(); i++)
    if (n.Get(i)->GetNodeType() == 0)
      return DynamicCast<QbbNetDevice>(n.Get(i)->GetDevice(1))
          ->GetDataRate()
          .GetBitRate();
}

bool ReadConf(string network_configuration) {
  // Read the configuration file
  std::ifstream conf;
  conf.open(network_configuration);
  if (!conf.is_open()) {
    std::cout << "Error: cannot find network config file: " << network_configuration << std::endl;
    fflush(stdout);
    return false;
  }
  
  while (!conf.eof()) {
    std::string key;
    conf >> key;

    if (key.compare("ENABLE_QCN") == 0) {
      uint32_t v;
      conf >> v;
      enable_qcn = v;
    } else if (key.compare("USE_DYNAMIC_PFC_THRESHOLD") == 0) {
      uint32_t v;
      conf >> v;
      use_dynamic_pfc_threshold = v;
    } else if (key.compare("CLAMP_TARGET_RATE") == 0) {
      uint32_t v;
      conf >> v;
      clamp_target_rate = v;
    } else if (key.compare("PAUSE_TIME") == 0) {
      double v;
      conf >> v;
      pause_time = v;
    } else if (key.compare("PACKET_PAYLOAD_SIZE") == 0) {
      uint32_t v;
      conf >> v;
      packet_payload_size = v;
    } else if (key.compare("L2_CHUNK_SIZE") == 0) {
      uint32_t v;
      conf >> v;
      l2_chunk_size = v;
    } else if (key.compare("L2_ACK_INTERVAL") == 0) {
      uint32_t v;
      conf >> v;
      l2_ack_interval = v;
    } else if (key.compare("L2_BACK_TO_ZERO") == 0) {
      uint32_t v;
      conf >> v;
      l2_back_to_zero = v;
    } else if (key.compare("TOPOLOGY_FILE") == 0) {
      std::string v;
      conf >> v;
      topology_file = v;
    } else if (key.compare("FLOW_FILE") == 0) {
      std::string v;
      conf >> v;
      flow_file = v;
    } else if (key.compare("TRACE_FILE") == 0) {
      std::string v;
      conf >> v;
      trace_file = v;
    } else if (key.compare("TRACE_OUTPUT_FILE") == 0) {
      std::string v;
      conf >> v;
      trace_output_file = v;
      // Removed to handle new command line arguments in build.sh.
  //if (argc > 2) {
      //  trace_output_file = trace_output_file + std::string(argv[2]);
      //}
    } else if (key.compare("SIMULATOR_STOP_TIME") == 0) {
      double v;
      conf >> v;
      simulator_stop_time = v;
    } else if (key.compare("ALPHA_RESUME_INTERVAL") == 0) {
      double v;
      conf >> v;
      alpha_resume_interval = v;
    } else if (key.compare("RP_TIMER") == 0) {
      double v;
      conf >> v;
      rp_timer = v;
    } else if (key.compare("EWMA_GAIN") == 0) {
      double v;
      conf >> v;
      ewma_gain = v;
    } else if (key.compare("FAST_RECOVERY_TIMES") == 0) {
      uint32_t v;
      conf >> v;
      fast_recovery_times = v;
    } else if (key.compare("RATE_AI") == 0) {
      std::string v;
      conf >> v;
      rate_ai = v;
    } else if (key.compare("RATE_HAI") == 0) {
      std::string v;
      conf >> v;
      rate_hai = v;
    } else if (key.compare("ERROR_RATE_PER_LINK") == 0) {
      double v;
      conf >> v;
      error_rate_per_link = v;
    } else if (key.compare("CC_MODE") == 0) {
      conf >> cc_mode;
    } else if (key.compare("RATE_DECREASE_INTERVAL") == 0) {
      double v;
      conf >> v;
      rate_decrease_interval = v;
    } else if (key.compare("MIN_RATE") == 0) {
      conf >> min_rate;
    } else if (key.compare("FCT_OUTPUT_FILE") == 0) {
      conf >> fct_output_file;
    } else if (key.compare("COMM_EVENTS_FILE") == 0) {
      conf >> comm_events_file;
    } else if (key.compare("CC_TELEMETRY_FILE") == 0) {
      conf >> cc_telemetry_file;
    } else if (key.compare("LOCAL_ECN_MARK_FILE") == 0) {
      conf >> local_ecn_mark_file;
    } else if (key.compare("LINK_TIMESERIES_FILE") == 0) {
      conf >> link_timeseries_file;
    } else if (key.compare("LINK_SUMMARY_FILE") == 0) {
      conf >> link_summary_file;
    } else if (key.compare("LINK_TELEMETRY_INTERVAL_NS") == 0) {
      conf >> link_telemetry_interval_ns;
    } else if (key.compare("KV_EP_NETWORK_POLICY") == 0) {
      conf >> kv_ep_network_policy;
    } else if (key.compare("HAS_WIN") == 0) {
      conf >> has_win;
    } else if (key.compare("GLOBAL_T") == 0) {
      conf >> global_t;
    } else if (key.compare("MI_THRESH") == 0) {
      conf >> mi_thresh;
    } else if (key.compare("VAR_WIN") == 0) {
      uint32_t v;
      conf >> v;
      var_win = v;
    } else if (key.compare("FAST_REACT") == 0) {
      uint32_t v;
      conf >> v;
      fast_react = v;
    } else if (key.compare("U_TARGET") == 0) {
      conf >> u_target;
    } else if (key.compare("INT_MULTI") == 0) {
      conf >> int_multi;
    } else if (key.compare("RATE_BOUND") == 0) {
      uint32_t v;
      conf >> v;
      rate_bound = v;
    } else if (key.compare("ACK_HIGH_PRIO") == 0) {
      conf >> ack_high_prio;
    } else if (key.compare("DCTCP_RATE_AI") == 0) {
      conf >> dctcp_rate_ai;
    } else if (key.compare("NIC_TOTAL_PAUSE_TIME") == 0) {
      conf >> nic_total_pause_time;
    } else if (key.compare("PFC_OUTPUT_FILE") == 0) {
      conf >> pfc_output_file;
    } else if (key.compare("LINK_DOWN") == 0) {
      conf >> link_down_time >> link_down_A >> link_down_B;
    } else if (key.compare("ENABLE_TRACE") == 0) {
      conf >> enable_trace;
    } else if (key.compare("KMAX_MAP") == 0) {
      int n_k;
      conf >> n_k;
      for (int i = 0; i < n_k; i++) {
        uint64_t rate;
        uint32_t k;
        conf >> rate >> k;
        rate2kmax[rate] = k;
      }
    } else if (key.compare("KMIN_MAP") == 0) {
      int n_k;
      conf >> n_k;
      for (int i = 0; i < n_k; i++) {
        uint64_t rate;
        uint32_t k;
        conf >> rate >> k;
        rate2kmin[rate] = k;
      }
    } else if (key.compare("PMAX_MAP") == 0) {
      int n_k;
      conf >> n_k;
      for (int i = 0; i < n_k; i++) {
        uint64_t rate;
        double p;
        conf >> rate >> p;
        rate2pmax[rate] = p;
      }
    } else if (key.compare("BUFFER_SIZE") == 0) {
      conf >> buffer_size;
    } else if (key.compare("QLEN_MON_FILE") == 0) {
      conf >> qlen_mon_file;
    } else if (key.compare("QLEN_MON_START") == 0) {
      conf >> qlen_mon_start;
    } else if (key.compare("QLEN_MON_END") == 0) {
      conf >> qlen_mon_end;
    } else if (key.compare("QLEN_MON_INTERVAL_NS") == 0) {
      conf >> qlen_mon_interval;
    } else if (key.compare("MULTI_RATE") == 0) {
      int v;
      conf >> v;
      multi_rate = v;
    } else if (key.compare("SAMPLE_FEEDBACK") == 0) {
      int v;
      conf >> v;
      sample_feedback = v;
    } else if (key.compare("PINT_LOG_BASE") == 0) {
      conf >> pint_log_base;
    } else if (key.compare("PINT_PROB") == 0) {
      conf >> pint_prob;
    }
    fflush(stdout);
  }
  conf.close();
  return true;
}

void SetConfig() {
  bool dynamicth = use_dynamic_pfc_threshold;

  Config::SetDefault("ns3::QbbNetDevice::PauseTime", UintegerValue(pause_time));
  Config::SetDefault("ns3::QbbNetDevice::QcnEnabled", BooleanValue(enable_qcn));
  Config::SetDefault("ns3::QbbNetDevice::DynamicThreshold",
                     BooleanValue(dynamicth));

  // set int_multi
  IntHop::multi = int_multi;
  // IntHeader::mode
  if (cc_mode == 7) // timely, use ts
    IntHeader::mode = IntHeader::TS;
  else if (cc_mode == 3) // hpcc, use int
    IntHeader::mode = IntHeader::NORMAL;
  else if (cc_mode == 10) // hpcc-pint
    IntHeader::mode = IntHeader::PINT;
  else // others, no extra header
    IntHeader::mode = IntHeader::NONE;

  // Set Pint
  if (cc_mode == 10) {
    Pint::set_log_base(pint_log_base);
    IntHeader::pint_bytes = Pint::get_n_bytes();
    printf("PINT bits: %d bytes: %d\n", Pint::get_n_bits(),
           Pint::get_n_bytes());
  }
}

bool SetupNetwork(void (*qp_finish)(FILE *, Ptr<RdmaQueuePair>)) {

  topof.open(topology_file.c_str());
  if (!topof.is_open()) {
    std::cerr << "Error: cannot open topology file: " << topology_file << std::endl;
    return false;
  }

  flowf.open(flow_file.c_str());
  if (!flowf.is_open()) {
    std::cerr << "Error: cannot open flow file: " << flow_file << std::endl;
    return false;
  }

  tracef.open(trace_file.c_str());
  if (!tracef.is_open()) {
    std::cerr << "Error: cannot open trace file: " << trace_file << std::endl;
    return false;
  }

  if (!comm_events_file.empty()) {
    comm_events_stream.open(comm_events_file.c_str(), std::ios::out | std::ios::trunc);
    if (!comm_events_stream.is_open()) {
      std::cerr << "Error: cannot open communication event file: "
                << comm_events_file << std::endl;
      return false;
    }
    comm_events_stream << "phase,event_id,request_id,collective_id,event_type,"
                          "layer_id,active_request_ids,serving_role,src,dst,port,tag,bytes,"
                          "priority_group,"
                          "issue_time_ns,network_start_ns,network_end_ns,"
                          "duration_ns,path,directed_link_ids,src_rank,dst_rank\n";
  }
  if (!cc_telemetry_file.empty()) {
    cc_telemetry_stream.open(cc_telemetry_file.c_str(),
                             std::ios::out | std::ios::trunc);
    if (!cc_telemetry_stream.is_open()) {
      std::cerr << "Error: cannot open congestion telemetry file: "
                << cc_telemetry_file << std::endl;
      return false;
    }
    cc_telemetry_stream
        << "timestamp,event,node_id,sip,dip,sport,dport,pg,bytes,"
           "old_rate_bps,new_rate_bps,target_rate_bps,reason,ecn_bits,qfb,total,"
           "qp_id,src_rank,dst_rank\n";
  }
  if (!local_ecn_mark_file.empty()) {
    local_ecn_mark_stream.open(local_ecn_mark_file.c_str(),
                               std::ios::out | std::ios::trunc);
    if (!local_ecn_mark_stream.is_open()) {
      std::cerr << "Error: cannot open local ECN mark file: "
                << local_ecn_mark_file << std::endl;
      return false;
    }
    local_ecn_mark_stream
        << "timestamp_ns,switch_id,link_id,next_node,egress_port,queue_index,"
           "mmu_egress_bytes_after_dequeue,kmin_bytes,kmax_bytes,packet_uid,"
           "ecn_before,sip,dip,sport,dport,udp_seq,traffic_class,event_ids,"
           "request_ids,collective_ids,layer_ids,qp_tuple\n";
  }
  if (!link_timeseries_file.empty()) {
    link_timeseries_stream.open(link_timeseries_file.c_str(),
                                std::ios::out | std::ios::trunc);
    if (!link_timeseries_stream.is_open()) {
      std::cerr << "Error: cannot open link telemetry file: "
                << link_timeseries_file << std::endl;
      return false;
    }
    link_timeseries_stream
        << "timestamp,link_id,src_node,dst_node,capacity_bps,tx_bytes,"
           "tx_packets,queue_bytes,queue_packets,ecn_marks,pfc_pause,"
           "drop_count\n";
  }
  if (!link_summary_file.empty()) {
    link_summary_stream.open(link_summary_file.c_str(),
                             std::ios::out | std::ios::trunc);
    if (!link_summary_stream.is_open()) {
      std::cerr << "Error: cannot open link summary file: "
                << link_summary_file << std::endl;
      return false;
    }
    link_summary_stream
        << "link_id,src_node,dst_node,capacity_bps,tx_bytes,tx_packets,"
           "simulation_end_ns,mean_utilization,peak_utilization,"
           "queue_max_bytes,queue_mean_bytes,ecn_marks,pfc_pause,drop_count\n";
  }

  uint32_t node_num, switch_num, link_num, trace_num;
  topof >> node_num >> switch_num >> link_num;
  flowf >> flow_num;
  tracef >> trace_num;
  link_telemetry_states.clear();
  link_telemetry_states.reserve(static_cast<size_t>(link_num) * 2);
  directed_link_ids.clear();
  topology_adjacency.clear();

  nbr2ifs.clear();
  std::vector<uint32_t> node_type(node_num, 0);
  for (uint32_t i = 0; i < switch_num; i++) {
    uint32_t sid;
    topof >> sid;
    node_type[sid] = 1;
  }
  for (uint32_t i = 0; i < node_num; i++) {
    if (node_type[i] == 0)
      n.Add(CreateObject<Node>());
    else {
      Ptr<SwitchNode> sw = CreateObject<SwitchNode>();
      n.Add(sw);
      sw->SetAttribute("EcnEnabled", BooleanValue(enable_qcn));
    }
  }

  if (local_ecn_mark_stream.is_open()) {
    for (uint32_t i = 0; i < n.GetN(); i++) {
      if (n.Get(i)->GetNodeType() != 1) continue;
      Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(i));
      const uint32_t switch_id = sw->GetId();
      sw->SetLocalEcnMarkCallback(
          [switch_id](uint32_t egress_port, uint32_t queue_index,
                      Ptr<const Packet> packet, uint32_t queue_bytes,
                      uint32_t kmin_bytes, uint32_t kmax_bytes) {
            telemetry_local_ecn_mark(switch_id, egress_port, queue_index,
                                     packet, queue_bytes, kmin_bytes,
                                     kmax_bytes);
          });
    }
  }

  NS_LOG_INFO("Create nodes.");

  InternetStackHelper internet;
  internet.Install(n);

  //
  // Assign IP to each server
  //
  for (uint32_t i = 0; i < node_num; i++) {
    if (n.Get(i)->GetNodeType() == 0) {
      serverAddress.resize(i + 1);
      serverAddress[i] = node_id_to_ip(i);
    }
  }

  NS_LOG_INFO("Create channels.");

  Ptr<RateErrorModel> rem = CreateObject<RateErrorModel>();
  Ptr<UniformRandomVariable> uv = CreateObject<UniformRandomVariable>();
  rem->SetRandomVariable(uv);
  uv->SetStream(50);
  rem->SetAttribute("ErrorRate", DoubleValue(error_rate_per_link));
  rem->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));

  FILE *pfc_file = fopen(pfc_output_file.c_str(), "w");

  QbbHelper qbb;
  Ipv4AddressHelper ipv4;
  for (uint32_t i = 0; i < link_num; i++) {
    uint32_t src, dst;
    std::string data_rate, link_delay;
    double error_rate;
    topof >> src >> dst >> data_rate >> link_delay >> error_rate;
    uint32_t forward_link_id = i * 2;
    uint32_t reverse_link_id = i * 2 + 1;
    directed_link_ids[{src, dst}] = forward_link_id;
    directed_link_ids[{dst, src}] = reverse_link_id;
    topology_adjacency[src].push_back(dst);
    topology_adjacency[dst].push_back(src);
    Ptr<Node> snode = n.Get(src), dnode = n.Get(dst);

    qbb.SetDeviceAttribute("DataRate", StringValue(data_rate));
    qbb.SetChannelAttribute("Delay", StringValue(link_delay));

    if (error_rate > 0) {
      Ptr<RateErrorModel> rem = CreateObject<RateErrorModel>();
      Ptr<UniformRandomVariable> uv = CreateObject<UniformRandomVariable>();
      rem->SetRandomVariable(uv);
      uv->SetStream(50);
      rem->SetAttribute("ErrorRate", DoubleValue(error_rate));
      rem->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));
      qbb.SetDeviceAttribute("ReceiveErrorModel", PointerValue(rem));
    } else {
      qbb.SetDeviceAttribute("ReceiveErrorModel", PointerValue(rem));
    }

    fflush(stdout);

    // Assigne server IP
    // Note: this should be before the automatic assignment below
    // (ipv4.Assign(d)), because we want our IP to be the primary IP (first in
    // the IP address list), so that the global routing is based on our IP
    NetDeviceContainer d = qbb.Install(snode, dnode);
    auto register_link = [&](uint32_t link_id, uint32_t link_src,
                             uint32_t link_dst, Ptr<QbbNetDevice> device) {
      if (device == nullptr || device->GetQueue() == nullptr) return;
      LinkTelemetryState state;
      state.link_id = link_id;
      state.src = link_src;
      state.dst = link_dst;
      state.capacity_bps = device->GetDataRate().GetBitRate();
      state.device = device;
      link_telemetry_states.push_back(state);
      LinkTelemetryState* telemetry = &link_telemetry_states.back();
      device->GetQueue()->TraceConnectWithoutContext(
          "BeqEnqueue", MakeBoundCallback(&telemetry_beq_enqueue, telemetry));
      device->GetQueue()->TraceConnectWithoutContext(
          "BeqDequeue", MakeBoundCallback(&telemetry_beq_dequeue, telemetry));
      device->TraceConnectWithoutContext(
          "PhyTxBegin", MakeBoundCallback(&telemetry_phy_tx_begin, telemetry));
      device->TraceConnectWithoutContext(
          "QbbDrop", MakeBoundCallback(&telemetry_qbb_drop, telemetry));
      device->TraceConnectWithoutContext(
          "QbbPfc", MakeBoundCallback(&telemetry_pfc, telemetry));
    };
    // Retain every physical interface for ECMP.  The single-value nbr2if map
    // is only a representative link for legacy distance/link-down helpers.
    Interface forward;
    forward.idx = DynamicCast<QbbNetDevice>(d.Get(0))->GetIfIndex();
    forward.up = true;
    forward.delay = DynamicCast<QbbChannel>(
        DynamicCast<QbbNetDevice>(d.Get(0))->GetChannel())
        ->GetDelay().GetTimeStep();
    forward.bw = DynamicCast<QbbNetDevice>(d.Get(0))
                     ->GetDataRate().GetBitRate();
    Interface reverse;
    reverse.idx = DynamicCast<QbbNetDevice>(d.Get(1))->GetIfIndex();
    reverse.up = true;
    reverse.delay = DynamicCast<QbbChannel>(
        DynamicCast<QbbNetDevice>(d.Get(1))->GetChannel())
        ->GetDelay().GetTimeStep();
    reverse.bw = DynamicCast<QbbNetDevice>(d.Get(1))
                     ->GetDataRate().GetBitRate();
    nbr2ifs[snode][dnode].push_back(forward);
    nbr2ifs[dnode][snode].push_back(reverse);
    nbr2if[snode][dnode] = forward;
    nbr2if[dnode][snode] = reverse;
    register_link(forward_link_id, src, dst,
                  DynamicCast<QbbNetDevice>(d.Get(0)));
    register_link(reverse_link_id, dst, src,
                  DynamicCast<QbbNetDevice>(d.Get(1)));

    // This is just to set up the connectivity between nodes. The IP addresses
    // are useless
    char ipstring[16];
    sprintf(ipstring, "10.%d.%d.0", i / 254 + 1, i % 254 + 1);
    ipv4.SetBase(ipstring, "255.255.255.0");
    ipv4.Assign(d);

    // setup PFC trace
    DynamicCast<QbbNetDevice>(d.Get(0))->TraceConnectWithoutContext(
        "QbbPfc", MakeBoundCallback(&get_pfc, pfc_file,
                                    DynamicCast<QbbNetDevice>(d.Get(0))));
    DynamicCast<QbbNetDevice>(d.Get(1))->TraceConnectWithoutContext(
        "QbbPfc", MakeBoundCallback(&get_pfc, pfc_file,
                                    DynamicCast<QbbNetDevice>(d.Get(1))));
  }

  if (cc_telemetry_stream.is_open() || link_summary_stream.is_open() ||
      link_timeseries_stream.is_open()) {
    Simulator::ScheduleDestroy(&finalize_link_telemetry);
  }

  nic_rate = get_nic_rate(n);
  // config switch
  for (uint32_t i = 0; i < node_num; i++) {
    if (n.Get(i)->GetNodeType() == 1) { // is switch
      Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(i));
      uint32_t shift = 3; // by default 1/8

      for (uint32_t j = 1; j < sw->GetNDevices(); j++) {
        Ptr<QbbNetDevice> dev = DynamicCast<QbbNetDevice>(sw->GetDevice(j));
        // set ecn
        uint64_t rate = dev->GetDataRate().GetBitRate();
        NS_ASSERT_MSG(rate2kmin.find(rate) != rate2kmin.end(),
                      "must set kmin for each link speed");
        NS_ASSERT_MSG(rate2kmax.find(rate) != rate2kmax.end(),
                      "must set kmax for each link speed");
        NS_ASSERT_MSG(rate2pmax.find(rate) != rate2pmax.end(),
                      "must set pmax for each link speed");
        sw->m_mmu->ConfigEcn(j, rate2kmin[rate], rate2kmax[rate],
                             rate2pmax[rate]);
        // set pfc
        uint64_t delay = DynamicCast<QbbChannel>(dev->GetChannel())
                             ->GetDelay()
                             .GetTimeStep();
        // uint32_t headroom = 150000; // rate * delay / 8 / 1000000000 * 3;
        uint32_t headroom = rate * delay / 8 / 1000000000 * 3;
        sw->m_mmu->ConfigHdrm(j, headroom);

        // set pfc alpha, proportional to link bw
        sw->m_mmu->pfc_a_shift[j] = shift;
        while (rate > nic_rate && sw->m_mmu->pfc_a_shift[j] > 0) {
          sw->m_mmu->pfc_a_shift[j]--;
          rate /= 2;
        }
      }
      sw->m_mmu->ConfigNPort(sw->GetNDevices() - 1);
      sw->m_mmu->ConfigBufferSize(buffer_size * 1024 * 1024);
      sw->m_mmu->node_id = sw->GetId();
    }
  }

#if ENABLE_QP
  FILE *fct_output = fopen(fct_output_file.c_str(), "w");
  std::cout << "QP is enabled " << std::endl;
  //
  // install RDMA driver
  //
  for (uint32_t i = 0; i < node_num; i++) {
    if (n.Get(i)->GetNodeType() == 0) { // is server
      // create RdmaHw
      Ptr<RdmaHw> rdmaHw = CreateObject<RdmaHw>();
      rdmaHw->SetAttribute("ClampTargetRate", BooleanValue(clamp_target_rate));
      rdmaHw->SetAttribute("AlphaResumInterval",
                           DoubleValue(alpha_resume_interval));
      rdmaHw->SetAttribute("RPTimer", DoubleValue(rp_timer));
      rdmaHw->SetAttribute("FastRecoveryTimes",
                           UintegerValue(fast_recovery_times));
      rdmaHw->SetAttribute("EwmaGain", DoubleValue(ewma_gain));
      rdmaHw->SetAttribute("RateAI", DataRateValue(DataRate(rate_ai)));
      rdmaHw->SetAttribute("RateHAI", DataRateValue(DataRate(rate_hai)));
      rdmaHw->SetAttribute("L2BackToZero", BooleanValue(l2_back_to_zero));
      rdmaHw->SetAttribute("L2ChunkSize", UintegerValue(l2_chunk_size));
      rdmaHw->SetAttribute("L2AckInterval", UintegerValue(l2_ack_interval));
      rdmaHw->SetAttribute("CcMode", UintegerValue(cc_mode));
      rdmaHw->SetAttribute("RateDecreaseInterval",
                           DoubleValue(rate_decrease_interval));
      rdmaHw->SetAttribute("MinRate", DataRateValue(DataRate(min_rate)));
      rdmaHw->SetAttribute("Mtu", UintegerValue(packet_payload_size));
      rdmaHw->SetAttribute("MiThresh", UintegerValue(mi_thresh));
      rdmaHw->SetAttribute("VarWin", BooleanValue(var_win));
      rdmaHw->SetAttribute("FastReact", BooleanValue(fast_react));
      rdmaHw->SetAttribute("MultiRate", BooleanValue(multi_rate));
      rdmaHw->SetAttribute("SampleFeedback", BooleanValue(sample_feedback));
      rdmaHw->SetAttribute("TargetUtil", DoubleValue(u_target));
      rdmaHw->SetAttribute("RateBound", BooleanValue(rate_bound));
      rdmaHw->SetAttribute("DctcpRateAI",
                           DataRateValue(DataRate(dctcp_rate_ai)));
      rdmaHw->SetPintSmplThresh(pint_prob);
      rdmaHw->SetAttribute("TotalPauseTimes",
                           UintegerValue(nic_total_pause_time));
      // create and install RdmaDriver
      Ptr<RdmaDriver> rdma = CreateObject<RdmaDriver>();
      Ptr<Node> node = n.Get(i);
      rdma->SetNode(node);
      rdma->SetRdmaHw(rdmaHw);

      node->AggregateObject(rdma);
      rdma->Init();
      rdma->TraceConnectWithoutContext(
          "QpComplete", MakeBoundCallback(qp_finish, fct_output));
      rdmaHw->TraceConnectWithoutContext("CnpReceived",
                                         MakeCallback(&telemetry_cnp));
      rdmaHw->TraceConnectWithoutContext("RateChange",
                                         MakeCallback(&telemetry_rate));
      rdmaHw->TraceConnectWithoutContext("QpMessageStart",
                                         MakeCallback(&telemetry_qp_message));
    }
  }
#endif


  // set ACK priority on hosts
  if (ack_high_prio)
    RdmaEgressQueue::ack_q_idx = 0;
  else
    RdmaEgressQueue::ack_q_idx = 3;

  // setup routing
  CalculateRoutes(n);
  SetRoutingEntries();

  //
  // get BDP and delay
  //
  maxRtt = maxBdp = 0;
  for (uint32_t i = 0; i < node_num; i++) {
    if (n.Get(i)->GetNodeType() != 0)
      continue;
    for (uint32_t j = 0; j < node_num; j++) {
      if (n.Get(j)->GetNodeType() != 0)
        continue;
      uint64_t delay = pairDelay[n.Get(i)][n.Get(j)];
      uint64_t txDelay = pairTxDelay[n.Get(i)][n.Get(j)];
      uint64_t rtt = delay * 2 + txDelay;
      uint64_t bw = pairBw[i][j];
      uint64_t bdp = rtt * bw / 1000000000 / 8;
      pairBdp[n.Get(i)][n.Get(j)] = bdp;
      pairRtt[i][j] = rtt;
      if (bdp > maxBdp)
        maxBdp = bdp;
      if (rtt > maxRtt)
        maxRtt = rtt;
    }
  }
  printf("maxRtt=%lu maxBdp=%lu\n", maxRtt, maxBdp);

  //
  // setup switch CC
  //
  for (uint32_t i = 0; i < node_num; i++) {
    if (n.Get(i)->GetNodeType() == 1) { // switch
      Ptr<SwitchNode> sw = DynamicCast<SwitchNode>(n.Get(i));
      sw->SetAttribute("CcMode", UintegerValue(cc_mode));
      sw->SetAttribute("MaxRtt", UintegerValue(maxRtt));
    }
  }

  //
  // add trace
  //

  NodeContainer trace_nodes;
  for (uint32_t i = 0; i < trace_num; i++) {
    uint32_t nid;
    tracef >> nid;
    if (nid >= n.GetN()) {
      continue;
    }
    trace_nodes = NodeContainer(trace_nodes, n.Get(nid));
  }

  FILE *trace_output = fopen(trace_output_file.c_str(), "w");
  if (enable_trace)
    qbb.EnableTracing(trace_output, trace_nodes);

  // dump link speed to trace file
  {
    SimSetting sim_setting;
    for (auto i : nbr2if) {
      for (auto j : i.second) {
        uint16_t node = i.first->GetId();
        uint8_t intf = j.second.idx;
        uint64_t bps =
            DynamicCast<QbbNetDevice>(i.first->GetDevice(j.second.idx))
                ->GetDataRate()
                .GetBitRate();
        sim_setting.port_speed[node][intf] = bps;
      }
    }
    sim_setting.win = maxBdp;
    sim_setting.Serialize(trace_output);
  }

#ifndef KVEP_REPLAY_SKIP_GLOBAL_ROUTING
  Ipv4GlobalRoutingHelper::PopulateRoutingTables();
#endif

  NS_LOG_INFO("Create Applications.");

  Time interPacketInterval = Seconds(0.0000005 / 2);
  // maintain port number for each host
  for (uint32_t i = 0; i < node_num; i++) {
    if (n.Get(i)->GetNodeType() == 0)
      for (uint32_t j = 0; j < node_num; j++) {
        if (n.Get(j)->GetNodeType() == 0)
          portNumber[i][j] = 10000; // each host pair use port number from 10000
      }
  }
  flow_input.idx = -1;

  topof.close();
  tracef.close();

  // schedule link down
  if (link_down_time > 0) {
    Simulator::Schedule(Seconds(2) + MicroSeconds(link_down_time),
                        &TakeDownLink, n, n.Get(link_down_A),
                        n.Get(link_down_B));
  }

  // schedule buffer monitor
  FILE *qlen_output = fopen(qlen_mon_file.c_str(), "w");
  Simulator::Schedule(NanoSeconds(qlen_mon_start), &monitor_buffer, qlen_output,
                      &n);

  return true;
}
