#!/usr/bin/env python

import sys
import time
from collections import deque
from itertools import ifilter

#import gi
#from gi.repository import GObject
##gi.require_version('gst', '1.0')
#gi.require_version('gst', '0.10')
#
#from gi.repository import gst
#from gi.repository import gtk
#from gi.repository import GLib

import gobject
import gst
import glib
import gtk

gobject.threads_init()
gtk.gdk.threads_init()

INPUT_COUNT = 1
# seconds
WINDOW_LENGTH = 1.5
UPDATE_INTERVAL = .25
MIN_ON_AIR_TIME = 3
# dB
NOISE_BASELINE = -45
SPEAK_UP_THRESHOLD = 3


class App(object):
    def __init__(self):
        self.current_input = 0
        self.last_switch_time = time.time()

        self.pipeline = pipeline = gst.Pipeline ('pipeline')

##        self.inputsel = gst.element_factory_make ('input-selector', None)
##        self.vsink = gst.element_factory_make ('autovideosink', None)
##        self.vsink_preview = gst.element_factory_make ('autovideosink', None)
##        self.vmixer = gst.element_factory_make ('videomixer', None)
##        self.vmixerq = gst.element_factory_make ('queue2', 'vmixer Q')

        self.asink = gst.element_factory_make ('autoaudiosink', None)
        #self.asink = gst.element_factory_make ('fakesink', None)


##        self.pipeline.add (self.vsink)
##        self.pipeline.add (self.vsink_preview)
##        self.pipeline.add (self.vmixer)
##        self.pipeline.add (self.vmixerq)
##        self.pipeline.add (self.inputsel)
##
##        self.inputsel.link (self.vsink)
##        self.vmixer.link (self.vmixerq)
##        self.vmixerq.link (self.vsink_preview)


        self.audio_inputs = []
        self.audio_queues = []
        self.audio_tees = []
        self.audio_avg = []
        self.audio_peak = []
        self.fasinks = []

        self.video_inputs = []
# XXX FIXME: ver en add_video_source
        self.video_tees = []
        self.video_queues = []
        self.volumes = []

        self.levels = []
        #self.amixer = gst.element_factory_make ('adder', None)

        #self.pipeline.add(self.amixer)
        self.pipeline.add(self.asink)

        #self.amixer.link(self.asink)

        for idx in range(INPUT_COUNT):
            continue
            dev = '/dev/video%d' % idx
            self.add_video_source(props=[('device', dev)])

        for idx in range(INPUT_COUNT):
#            if idx==0:
#                self.add_audio_source('alsasrc', [('device', 'hw:1,0')] )
#                continue

            freq = 440*(idx+1)
            print freq
            self.add_audio_source(props=[('freq', freq), ('is-live', True)])

#        for idx,pad in enumerate(self.vmixer.sinkpads):
#            pad.set_property('ypos' , 0)
#            pad.set_property('xpos' , 320*idx)

    def add_audio_source (self, sourcename=None, props=None):
        # 10 samples per second
        self.audio_avg.append (deque (maxlen=WINDOW_LENGTH * 10))
        self.audio_peak.append (deque (maxlen=WINDOW_LENGTH * 10))

        name = sourcename or 'audiotestsrc'
        src = gst.element_factory_make (name, None)
        self.pipeline.add (src)
        src.link (self.asink)
        return
        q0 = gst.element_factory_make ('queue2', None)
        q1 = gst.element_factory_make ('queue2', None)
        tee = gst.element_factory_make ('tee', None)
        volume = gst.element_factory_make ('volume', None)

        fasink = gst.element_factory_make ('fakesink', None)
        fasink.set_property ('sync', True)

        level = gst.element_factory_make ('level', None)
        level.set_property ("message", True)

        self.pipeline.add (q0)
        self.pipeline.add (q1)
        self.pipeline.add (tee)
        self.pipeline.add (volume)
        self.pipeline.add (fasink)
        self.pipeline.add (level)

        if props:
            for prop,val in props:
                src.set_property (prop, val)

        caps = gst.Caps ('audio/x-raw-int,rate=32000,channels=2')
        src.link_filtered (self.asink, caps)
        q1.link (volume)
        volume.link (tee)
        tee.link (q0)
        q0.link (self.amixer)
        tee.link (level)
        level.link(fasink)

        self.audio_inputs.append (src)
        self.audio_queues.append (q0)
        self.audio_tees.append (tee)
        self.levels.append (level)
        self.volumes.append (volume)
        self.fasinks.append (fasink)

    def add_video_source (self, sourcename=None, props=None):
        name = sourcename or 'v4l2src'
        src = gst.element_factory_make (name, None)
        q0 = gst.element_factory_make ('queue2', None)
        q1 = gst.element_factory_make ('queue2', None)
        tee = gst.element_factory_make ('tee', None)

        self.pipeline.add (src)
        self.pipeline.add (q0)
        self.pipeline.add (q1)
        self.pipeline.add (tee)

        if props:
            for prop,val in props:
                src.set_property(prop, val)

# XXX: aca usar el pad de preview de uvch264 en lugar de un tee con lo mismo
        src.link(tee)
        tee.link(q0)
        tee.link(q1)
        q0.link(self.inputsel)
        q1.link(self.vmixer)
        self.video_inputs.append(src)
        self.video_queues.append(q0)
        self.video_queues.append(q1)
        self.video_tees.append(tee)

    def set_channel_volume(self, chanidx, volume):
        if volume > 1.5:
            volume = 1.5
        elif volume < 0:
            volume = 0

        try:
            self.volumes[chanidx].set_property('volume', volume)
        except IndexError:
            pass

    def set_active_input(self, inputidx):
        isel = self.inputsel
        oldpad = isel.get_property ('active-pad')
        # pads[0] output, rest input sinks.
        idx = 1 + (inputidx % (len(isel.pads)-1))

        newpad = isel.pads[idx]
        self.current_input = inputidx
        if idx != isel.pads.index(oldpad):
            isel.set_property('active-pad', newpad)

    def toggle (self, *args):
        e = self.inputsel
        s = e.get_property ('active-pad')
        # pads[0] output, rest input sinks.
        # set_active_input() uses 0..N, so this works out to switch to the next
        i = e.pads.index(s)
        self.set_active_input(i)

    def start (self):
        self.pipeline.set_state (gst.STATE_PLAYING)
        bus = self.pipeline.get_bus()
# signals are kind of broken on gst 0.10
# https://bugzilla.gnome.org/show_bug.cgi?id=631901
#        bus.add_signal_watch()
#        bus.connect("message::element", self.bus_element_cb)
#        bus.connect("message", self.bus_message_cb)
        self.tid = glib.timeout_add(int (UPDATE_INTERVAL * 1000), self.process_levels)
        #self.watch_id = bus.add_watch_full (GLib.PRIORITY_DEFAULT, self.bus_message_cb, None);

# XXX: devolver True, sino el timeout se destruye
    def process_levels (self):
        return True
        now = time.time()
        def do_switch (src):
            if src == self.current_input:
                return
            self.last_switch_time = now
            self.set_active_input (src)
            print 'DO_SWITCH ', src

        if (now - self.last_switch_time) < MIN_ON_AIR_TIME:
            return True
        print 'PROCESS current_input ', self.current_input
        dpeaks = []
        avgs = []
        for idx,q in enumerate (self.audio_avg):
            avgs.append ( (idx, sum (q) / (10*WINDOW_LENGTH)) )

        for idx,q in enumerate (self.audio_avg):
            dp = []
            for (x1,x2) in zip (q, list(q)[1:]):
                dp.append (x2-x1)
            dpeaks.append ( (idx, sum(dp) / (10*(WINDOW_LENGTH-1))) )

# ver caso si mas de uno pasa umbral.
        peaks_over = filter (lambda x: x[1] > SPEAK_UP_THRESHOLD, dpeaks)
        if peaks_over:
            idx, peak = max (peaks_over, key= lambda x: x[1])
            print ' PEAKS OVER ', peaks_over
            do_switch (idx)
            return True

        idx, avg = max (avgs, key= lambda x: x[1])
        do_switch (idx)
        #return True

        print ' AVGs ', avgs , ' dPEAKs ', dpeaks
        return True

    def bus_message_cb (self, bus, msg, arg=None):
        if msg.type == gst.MessageType.CLOCK_LOST:
            self.pipeline.set_state (gst.State.PAUSED)
            self.pipeline.set_state (gst.State.PLAYING)

    def bus_element_cb (self, bus, msg, arg=None):
        s = msg.get_structure()
        if s.get_name() != "level":
            return
        idx = self.levels.index (msg.src)
        print 'RMS ', s.get_value('rms')
        self.audio_avg[idx].append (s.get_value ('rms')[0])
        self.audio_peak[idx].append (s.get_value ('peak')[0])

if __name__ == "__main__":

    app = App()


    app.start()
    gst.DEBUG_BIN_TO_DOT_FILE(app.pipeline, gst.DEBUG_GRAPH_SHOW_NON_DEFAULT_PARAMS | gst.DEBUG_GRAPH_SHOW_MEDIA_TYPE | gst.DEBUG_GRAPH_SHOW_CAPS_DETAILS, 'debug1')

#    gst.debug_bin_to_dot_file(app.pipeline, gst.DebugGraphDetails.MEDIA_TYPE | gst.DebugGraphDetails.NON_DEFAULT_PARAMS , 'debug1')
##    gst.debug_bin_to_dot_file(app.pipeline, gst.DebugGraphDetails.MEDIA_TYPE | gst.DebugGraphDetails.NON_DEFAULT_PARAMS | gst.DebugGraphDetails.CAPS_DETAILS, 'debug1')
#

    gtk.main()
    sys.exit(0)
