/******************************************************************************
This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
*******************************************************************************/

#ifndef __COMMON_HH__
#define __COMMON_HH__

#include <cstdint>
#include <string>

namespace AstraSim {

typedef unsigned long long Tick;

constexpr uint64_t CLOCK_PERIOD = 1;           // 1ns
constexpr uint64_t FREQ = 1000 * 1000 * 1000;  // 1GHz
// A communication node may represent a batch rather than one request.  Keep
// that distinct from request 0 in backend telemetry.
constexpr uint64_t NO_REQUEST_ID = static_cast<uint64_t>(-1);

enum time_type_e { SE = 0, MS, US, NS, FS };

enum req_type_e { UINT8 = 0, BFLOAT16, FP32 };

enum network_event_type_e : uint32_t {
    NETWORK_EVENT_UNKNOWN = 0,
    NETWORK_EVENT_P2D_KV = 1,
    NETWORK_EVENT_EP_DISPATCH = 2,
    NETWORK_EVENT_EP_COMBINE = 3,
};

struct timespec_t {
    time_type_e time_res;
    long double time_val;
};

struct sim_request {
    uint32_t srcRank = 0;
    uint32_t dstRank = 0;
    uint32_t tag = 0;
    req_type_e reqType = UINT8;
    uint64_t reqCount = 0;
    uint32_t vnet = 0;
    uint32_t layerNum = 0;
    // Optional serving/network provenance. ``NO_REQUEST_ID`` means this is a
    // batch aggregate; ``activeRequestIds`` then carries the full id list.
    uint64_t requestId = NO_REQUEST_ID;
    uint64_t collectiveId = 0;
    uint32_t eventType = 0;
    std::string activeRequestIds;
    std::string servingRole;
};

class MetaData {
  public:
    timespec_t timestamp;
};

enum class ComType {
    None = 0,
    Reduce_Scatter,
    All_Gather,
    All_Reduce,
    All_to_All,
    All_Reduce_All_to_All
};

enum class CollectiveOptimization { Baseline = 0, LocalBWAware };

enum class CollectiveImplType {
    Ring = 0,
    OneRing,
    Direct,
    OneDirect,
    AllToAll,
    DoubleBinaryTreeLocalAllToAll,
    LocalRingNodeA2AGlobalDBT,
    HierarchicalRing,
    DoubleBinaryTree,
    HalvingDoubling,
    OneHalvingDoubling,
    ChakraImpl,
};

enum class CollectiveBarrier { Blocking = 0, Non_Blocking };

enum class SchedulingPolicy { LIFO = 0, FIFO, EXPLICIT, None };

enum class IntraDimensionScheduling {
    FIFO = 0,
    RG,
    SmallestFirst,
    LessRemainingPhaseFirst
};

enum class InterDimensionScheduling {
    Ascending = 0,
    OnlineGreedy,
    RoundRobin,
    OfflineGreedy,
    OfflineGreedyFlex
};

enum class InjectionPolicy {
    Infinite = 0,
    Aggressive,
    SemiAggressive,
    ExtraAggressive,
    Normal
};

enum class PacketRouting { Hardware = 0, Software };

enum class BusType { Both = 0, Shared, Mem };

enum class StreamState {
    Created = 0,
    Transferring,
    Ready,
    Executing,
    Zombie,
    Dead
};

enum class EventType {
    CallEvents = 0,
    General,
    RendezvousSend,
    RendezvousRecv,
    PacketReceived,
    PacketSent,
    Rec_Finished,
    Send_Finished,
    Processing_Finished,
    NPU_to_MA,
    MA_to_NPU,
    Consider_Process,
    Consider_Retire,
    Consider_Send_Back,
    StreamInit,
    CommProcessingFinished,
    CollectiveCommunicationFinished,
    CompFinished,
    MemLoadFinished,
    MemStoreFinished
};

class CloneInterface {
  public:
    virtual CloneInterface* clone() const = 0;
    virtual ~CloneInterface() = default;
};

/*
 * CollectiveImpl holds the user's description on how a collective algorithm is
 * implemented, provided in the System layer input.
 */
class CollectiveImpl : public CloneInterface {
  public:
    CollectiveImpl(CollectiveImplType type) {
        this->type = type;
    };
    virtual CloneInterface* clone() const {
        return new CollectiveImpl(*this);
    }

    CollectiveImplType type;
};

/*
 * DirectCollectiveImpl contains user-specified information about Direct
 * implementation of collective algorithms. We have a separte class for
 * DirectCollectiveImpl, because of the collective window, which is also defined
 * in the system layer input.
 */
class DirectCollectiveImpl : public CollectiveImpl {
  public:
    CloneInterface* clone() const {
        return new DirectCollectiveImpl(*this);
    };
    DirectCollectiveImpl(CollectiveImplType type, int direct_collective_window)
        : CollectiveImpl(type) {
        this->direct_collective_window = direct_collective_window;
    }

    int direct_collective_window;
};

/*
 * ChakraCollectiveImpl contains information about a collective implementation
 * represented using the Chakra ET format. It containes the filename of the
 * Chakra ET which holds the implementation, provided in the System layer input.
 */
class ChakraCollectiveImpl : public CollectiveImpl {
  public:
    CloneInterface* clone() const {
        return new ChakraCollectiveImpl(*this);
    };
    ChakraCollectiveImpl(CollectiveImplType type, std::string filename)
        : CollectiveImpl(type) {
        this->filename = filename;
    }

    /* The filename of the corresponding Chakra ET file */
    std::string filename;
};
}  // namespace AstraSim

#endif /* __COMMON_HH__ */
