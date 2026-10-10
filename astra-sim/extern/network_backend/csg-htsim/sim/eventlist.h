// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef EVENTLIST_H
#define EVENTLIST_H

#include <map>
#include <unordered_map>
#include <sys/time.h>
#include "config.h"
#include "loggertypes.h"

class EventList;
class TriggerTarget;

class EventSource : public Logged {
public:
    EventSource(EventList& eventlist, const string& name) : Logged(name), _eventlist(eventlist) {};
    EventSource(const string& name);
    virtual ~EventSource() {};
    virtual void doNextEvent() = 0;
    inline EventList& eventlist() const {return _eventlist;}
protected:
    EventList& _eventlist;
};

class EventList {
public:
    typedef multimap <simtime_picosec, EventSource*>::iterator Handle;
    EventList();
    static void setEndtime(simtime_picosec endtime); // end simulation at endtime (rather than forever)
    static bool doNextEvent(); // returns true if it did anything, false if there's nothing to do
    static void sourceIsPending(EventSource &src, simtime_picosec when);
    // Return whether an event for this source is currently present in the
    // pending-event set.  This is needed by stateful devices that can retain
    // packets across an interactive round boundary.  A round may temporarily
    // close the event-list end time, which can suppress a newly scheduled
    // event while the device's packet count remains non-zero.
    static bool hasPendingSource(const EventSource &src);
    static Handle sourceIsPendingGetHandle(EventSource &src, simtime_picosec when);
    static void sourceIsPendingRel(EventSource &src, simtime_picosec timefromnow)
    { sourceIsPending(src, EventList::now()+timefromnow); }
    static void cancelPendingSource(EventSource &src);
    // optimized cancel, if we know the expiry time
    static void cancelPendingSourceByTime(EventSource &src, simtime_picosec when);   
    // optimized cancel by handle - be careful to ensure handle is still valid
    static void cancelPendingSourceByHandle(EventSource &src, Handle handle);       
    static void reschedulePendingSource(EventSource &src, simtime_picosec when);
    static void triggerIsPending(TriggerTarget &target);
    static inline simtime_picosec now() {return EventList::_lasteventtime;}
    static Handle nullHandle() {return _pendingsources.end();}


    static EventList& getTheEventList();
    EventList(const EventList&)      = delete;  // disable Copy Constructor
    void operator=(const EventList&) = delete;  // disable Assign Constructor

private:
    static simtime_picosec _endtime;
    static simtime_picosec _lasteventtime;
    typedef multimap <simtime_picosec, EventSource*> pendingsources_t;
    static pendingsources_t _pendingsources;
    // Number of queued events per source.  This keeps hasPendingSource()
    // O(1); it is called on every packet arrival by stateful pipes.
    static unordered_map <const EventSource*, size_t> _pending_source_counts;
    static vector <TriggerTarget*> _pending_triggers;

    static int _instanceCount;
    static EventList* _theEventList;
};

#endif
