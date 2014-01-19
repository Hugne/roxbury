#!/usr/bin/env python
# ----------------------------------------------------------------------------
# "THE BEER-WARE LICENSE" (Revision 42):
# <fli@shapeshifter.se> wrote this file. As long as you retain this notice you
# can do whatever you want with this stuff. If we meet some day, and you think
# this stuff is worth it, you can buy me a beer in return Fredrik Lindberg
# ----------------------------------------------------------------------------
#

import os
import sys
import time
import signal
import select
import syslog
import random
from optparse import OptionParser

# Gstreamer python bindings
import pygst
import gst
import gobject

class Roxbury(object):
    def __init__(self, files, rand=False):
        self._files = files
        self._pos = -1
        self._rand = rand
        self.playing = False
        self._pl = gst.element_factory_make("playbin2", "player")
        self.next()
        self.bus = bus = self._pl.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

    def on_message(self, bus, message):
        t = message.type
        if t == gst.MESSAGE_EOS:
            self._pl.set_state(gst.STATE_NULL)
            self.next()
            self.play()
        elif t == gst.MESSAGE_ERROR:
            err, debug = message.parse_error()
            syslog.syslog(syslog.LOG_ERR, "{0}".format(err))
            syslog.syslog(syslog.LOG_DEBUG, "{0}".format(debug))
            self.stop()

    def poll(self):
        self.bus.poll(gst.MESSAGE_ANY, 0)

    def next(self):
        self._pos = (self._pos + 1) % len(self._files)
        if self._rand and self._pos == (len(self._files) - 1):
            self.shuffle()
        file = self._files[self._pos]
        self._pl.set_property('uri',
            'file://' + os.path.abspath(self._files[self._pos]))

    def shuffle(self):
        random.shuffle(self._files)

    def play(self):
        self.playing = True
        self._pl.set_state(gst.STATE_PLAYING)
        syslog.syslog("Playing {0}".format(self._files[self._pos]))

    def stop(self):
        self.playing = False
        self._pl.set_state(gst.STATE_NULL)
        syslog.syslog("Playpack stopped")

    def pause(self):
        self.playing = False
        self._pl.set_state(gst.STATE_PAUSED)
        syslog.syslog("Playback paused")

    def toggle(self):
        self.play() if not self.playing else self.pause()

class Signal(object):
    def __init__(self, signo):
        self._list = []
        signal.signal(signo, self.handler)

    def add(self, callback, argument=None):
        self._list.append((callback, argument))

    def handler(self, sig, frame):
        for (cb, arg) in self._list:
            cb(arg)

def main(fd, args):
    parser = OptionParser(usage="%prog [options] file1.mp3 [file2.mp3]")
    parser.add_option("-p", "--poll", dest="gpio", default=None,
                  help="GPIO poll")
    (opts, files) = parser.parse_args()

    if len(files) < 1:
        print "You need to specify at least one music file"
        return 0

    random.seed()

    p = None
    if opts.gpio:
        p = select.poll()
        file = open(opts.gpio, 'r')
        p.register(file, select.POLLPRI | select.POLLERR)

    roxbury = Roxbury(files, True)

    sigusr1 = Signal(signal.SIGUSR1)
    sigusr1.add((lambda x: roxbury.toggle()))

    sigusr2 = Signal(signal.SIGUSR2)
    sigusr2.add((lambda x: roxbury.next()))

    running = [True]
    def stop(x):
        syslog.syslog("Got SIGTERM/SIGINT, shuting down player")
        running[0] = False

    sigterm = Signal(signal.SIGTERM)
    sigterm.add(stop)
    sigint = Signal(signal.SIGINT)
    sigint.add(stop)

    syslog.syslog("Ready to dance")

    while running[0]:
        if fd:
            print >>fd, "emilio"
            fd.flush()
        roxbury.poll()
        if p:
            ready = p.poll(0.5)
            try:
                if len(ready) > 0:
                    (gpio_fd, event) = ready[0]
                    value = os.read(gpio_fd, 1)
                    roxbury.play() if int(value) == 1 else roxbury.pause()
                    os.lseek(gpio_fd, 0, os.SEEK_SET)
            except:
                ''
        else:
            time.sleep(0.5)

    return 0

def watchdog():
    r,w = os.pipe()
    r = os.fdopen(r, 'r', 0)
    w = os.fdopen(w, 'w', 0)

    pid = os.fork()
    if pid < 0:
        print "Fork failed"
        sys.exit(-1)
    elif pid == 0:
        sys.exit(main(w, sys.argv))

    running = [True]
    restart = False
    def stop(x):
        syslog.syslog("Got SIGTERM/SIGINT, shuting down watchdog")
        running[0] = False

    sigterm = Signal(signal.SIGTERM)
    sigterm.add(stop)
    sigint = Signal(signal.SIGINT)
    sigint.add(stop)
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    signal.signal(signal.SIGUSR2, signal.SIG_IGN)

    while running[0]:
        try:
            rr,rw,re = select.select([r], [], [], 2.5)
            if len(rr) > 0:
                r.readline()
            elif len(rr) == 0:
                (wpid, ret) = os.waitpid(pid, os.WNOHANG)
                if wpid == 0 or (wpid != 0 and ret != 0):
                    os.kill(pid, signal.SIGKILL)
                    restart = True
                    syslog.syslog("Not enough ass-grabbing, resetting")
                running[0] = False
                break
        except:
            ''

    r.close()
    try:
        os.waitpid(pid, os.WNOHANG)
    except:
        ''
    return restart

if __name__ == '__main__':
    restart = True
    while restart:
        restart = watchdog()
