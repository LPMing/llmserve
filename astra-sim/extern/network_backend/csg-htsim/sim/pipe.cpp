// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-        
#include "pipe.h"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>

namespace {

bool htsim_pipe_debug_flow(flowid_t flow_id) {
    return flow_id == 210 || (flow_id >= 225 && flow_id <= 232);
}

void htsim_pipe_debug(const char* kind, Pipe* pipe, const Packet& pkt,
                      int count) {
    const char* path = std::getenv("LLMSERVINGSIM_HTSIM_PIPE_DEBUG");
    if (path == nullptr || !htsim_pipe_debug_flow(pkt.flow().flow_id())) {
        return;
    }
    std::ofstream out(path, std::ios::app);
    out << kind << " t_ps=" << pipe->eventlist().now()
        << " flow_id=" << pkt.flow().flow_id()
        << " dst=" << pkt.dst()
        << " count=" << count
        << " pipe=" << pipe->nodename() << '\n';
}

}

Pipe::Pipe(simtime_picosec delay, EventList& eventlist)
: EventSource(eventlist,"pipe"), _delay(delay)
{
    _count = 0;
    _next_insert = 0;
    _next_pop = 0;
    _size = 16; // initial size; we'll resize if needed
    _inflight_v.resize(_size);
    stringstream ss;
    ss << "pipe(" << delay/1000000 << "us)";
    _nodename= ss.str();
}

void
Pipe::receivePacket(Packet& pkt)
{
    htsim_pipe_debug("PIPE_ARRIVE", this, pkt, _count);
    //pkt.flow().logTraffic(pkt,*this,TrafficLogger::PKT_ARRIVE);
    //if (_inflight.empty()){
    // HTSim is driven in interactive serving rounds.  A round can stop at
    // the same time that a packet is in flight: setting EventList's end time
    // suppresses the pipe's future event, but does not remove the packet from
    // this pipe's ring buffer.  In that state _count is non-zero while there
    // is no pending event, so the traditional `_count == 0` test permanently
    // strands the packet and all packets behind it.  Re-arm the pipe whenever
    // its state has no corresponding event.
    if (_count == 0 || !eventlist().hasPendingSource(*this)){
        /* no packets currently inflight; need to notify the eventlist
           we've an event pending */
            eventlist().sourceIsPendingRel(*this,_delay);
    }
    _count++;
    if (_count == _size) {
        _inflight_v.resize(_size*2);
        if (_next_insert < _next_pop) {
                //   456789*123
                // NI *, NP 1
            for (int i=0; i < _next_insert; i++) {
                // move 4-9 into new space
                _inflight_v.at(_size+i) = _inflight_v.at(i);
            }
            _next_insert += _size;
        } else {
            // 123456789*
            // nothing to do
        }
        _size += _size;
    }
    _inflight_v[_next_insert].time = eventlist().now() + _delay;
    _inflight_v[_next_insert].pkt = &pkt;
    _next_insert = (_next_insert +1) % _size;
    //_inflight.push_front(make_pair(eventlist().now() + _delay, &pkt));
}

void
Pipe::doNextEvent() {
    //if (_inflight.size() == 0) 
    if (_count == 0) 
            return;

    //Packet *pkt = _inflight.back().second;
    //_inflight.pop_back();
    Packet *pkt = _inflight_v[_next_pop].pkt;
    _next_pop = (_next_pop +1) % _size;
    _count--;
    htsim_pipe_debug("PIPE_EVENT", this, *pkt, _count);
    pkt->flow().logTraffic(*pkt, *this,TrafficLogger::PKT_DEPART);

    // tell the packet to move itself on to the next hop
    pkt->sendOn();

    //if (!_inflight.empty()) {
    if (_count > 0) {
        // notify the eventlist we've another event pending
        simtime_picosec nexteventtime = _inflight_v[_next_pop].time;
        _eventlist.sourceIsPending(*this, nexteventtime);
    }
}
