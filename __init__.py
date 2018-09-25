# -*- coding: utf8 -*-
"""
Contains a RPi GPIO library test mockup.

Currently the official GPIO is not fully implemented.
Never the less this module is useful
for the most common scenarios.
"""

import warnings
warnings.warn("You're currently using a GPIO mockup!")

import pathlib
import mmap
import threading
import traceback

class GPIODummy(object):

    CHANNEL_NAMES = {
        1: "3.3V",
        2: "5V",
        3: "SDA", 
        4: "5V",
        5: "SCL",
        6: "GND",
        7: "GPCLK0",
        8: "TXD",
        9: "GND",
        10: "RXD",
        11: "BCM17",
        12: "PWM0",
        13: "BCM27",
        14: "GND",
        15: "BCM22",
        16: "BCM23",
        17: "3.3V",
        18: "BCM24",
        19: "MOSI",
        20: "GND",
        21: "MISO",
        22: "BCM25",
        23: "SCLK",
        24: "CE0",
        25: "GND",
        26: "CE1",
        27: "ID_SD",
        28: "ID_SC",
        29: "BCM5",
        30: "GND",
        31: "BCM6",
        32: "PWM0",
        33: "PWM1",
        34: "GND",
        35: "MISO",
        36: "BCM16",
        37: "BCM26",
        38: "MOSI",
        39: "GND",
        40: "SCLK"
    }

    PIN_TO_GPIO = [
        -1, -1, -1, 2, -1, 3, -1, 4, 14, -1,
        15, 17, 18, 27, -1, 22, 23, -1, 24, 10,
        -1, 9, 25, 11, 8, -1, 7, -1, -1, 5,
        -1, 6, 12, 13, -1, 19, 16, 26, 20, -1,
        21
    ]

    GPIO_TO_PIN = dict((v, i) for i, v in enumerate(PIN_TO_GPIO) if v >= 0)

    UNDEFINED = 255

    HIGH = 1
    LOW = 0

    OUT = 0
    IN = 1

    PWM = 43
    SERIAL = 40
    I2C = 42
    SPI = 41

    MODE_UNKNOWN = -1
    BOARD = 10
    BCM = 11

    PUD_OFF = 20 + 0
    PUD_DOWN = 20 + 1
    PUD_UP = 20 + 2

    RISING = 30 + 1
    FALLING = 30 + 2
    BOTH = 30 + 3

    VALUE_OFFSET = 0
    DIRECTION_OFFSET = 53
    PUD_OFFSET = 106

    def __init__(self, mapfile = -1, initialize = False):
        """
        Initializes the GPIO instance.
        For `mapfile` and `initialize` see set_mapfile below.
        """
        self.mode = self.MODE_UNKNOWN
        self._warnings = True

        self._mapfile = None
        self.set_mapfile(mapfile, initialize)

        self._write_allowed = False

        self._watched_gpios = {}
        self._watcher_thread = threading.Thread(target = self, name = "gpio-watcher")
        self._watcher_thread.setDaemon(True)
        self._watcher_lock = threading.Lock()
        self._watcher_condition = threading.Condition(self._watcher_lock)
        self._watcher_shutdown = False
        self._detected_events = set()

        self._watcher_thread.start()

    # ---- [ Protected (internal) methods ] -------------------------------------------------------

    def _flush(self):
        self._mmap.flush()

    def _write(self, offset, value):
        assert (offset >= 0) and (offset < 159), "gpio offset error, %r not in range 0 .. 158." % (offset,)
        assert (value >= 0) and (value < 256), "value error, has to be in range 0 .. 255, is %r." % (value,)
        self._mmap[offset] = value
        self._flush()

    def _write_direction(self, gpio, direction):
        assert direction in (self.IN, self.OUT), "direction has to be IN or OUT, not %r" % (direction,)
        assert (gpio >= 0) and (gpio <= 53), "GPIO has to be in range 0 .. 53, is %r" % (gpio,)
        self._write(self.DIRECTION_OFFSET + gpio, direction)

    def _write_pud(self, gpio, pud):
        assert pud in (self.PUD_OFF, self.PUD_DOWN, self.PUD_UP), "pull_up_down has to be OFF, DOWN or UP, not %r!" % (pud,)
        assert (gpio >= 0) and (gpio <= 53), "GPIO has to be in range 0 .. 53, is %r" % (gpio,)
        self._write(self.PUD_OFFSET + gpio, pud)

    def _write_value(self, gpio, value):
        assert (value == self.HIGH) or (value == self.LOW), "value has to be HIGH or LOW, not %r!" % (value,)
        assert (gpio >= 0) and (gpio <= 53), "GPIO has to be in range 0 .. 53, is %r" % (gpio,)
        self._write(self.VALUE_OFFSET + gpio, value)

    def _read(self, offset):
        assert (offset >= 0) and (offset < 159), "gpio offset error, %r not in range 0 .. 158." % (offset,)
        return self._mmap[offset]

    def _read_direction(self, gpio):
        assert (gpio >= 0) and (gpio < 53)
        return self._read(self.DIRECTION_OFFSET + gpio)

    def _read_pud(self, gpio):
        assert (gpio >= 0) and (gpio < 53)
        return self._read(self.PUD_OFFSET + gpio)

    def _read_value(self, gpio):
        assert (gpio >= 0) and (gpio < 53)
        return self._read(self.VALUE_OFFSET + gpio)

    def _cleanup_all(self):
        raise NotImplementedError

    def _cleanup_one(self, gpio):
        assert gpio >= -1 and gpio <= 53
        if gpio != -1:
            self._event_cleanup(gpio)
            self._setup_gpio(gpio, self.IN, self.PUD_OFF)

    def _setup_gpio(self, gpio, mode, pud):
        assert gpio >= -1 and gpio <= 53
        if gpio != -1:
            self._write_direction(gpio, mode)
            self._write_pud(gpio, pud)
            return True
        return False

    def _output_gpio(self, gpio, value):
        assert gpio >= 0 and gpio <= 53
        assert self._write_allowed or (self._read_direction(gpio) == self.OUT)
        self._write_value(gpio, value)

    def _output_one(self, channel, value):
        gpio = self._get_gpio_number(channel)
        if (self._read_direction(gpio) != self.OUT) and not self._write_allowed:
            raise RuntimeError("Cannot output to channel %d, not in OUT direction!" % (channel,))
        self._output_gpio(gpio, value)

    def _setup_one(self, gpio, direction, pull_up_down = None, initial = None):
        assert gpio >= 0 and gpio <= 53
        if self._read_direction(gpio) != self.UNDEFINED:
            if self._warnings:
                warnings.warn("GPIO %d is already in use, continuing anyway. Use GPIO.setwarnings(False) to disable warnings." % (gpio,))
        self._write_direction(gpio, direction)
        self._write_pud(gpio, pull_up_down)
        if initial != None:
            self._write_value(gpio, initial)

    def _get_channel_number(self, gpio: int):
        if self.mode == self.BCM:
            return gpio
        if self.mode == self.BOARD:
            try:
                return self.GPIO_TO_PIN[gpio]
            except KeyError:
                pass
        return -1
        
    def _get_gpio_number(self, channel: int):
        if self.mode == self.BCM:
            if (channel < 0) or (channel > 53):
                raise ValueError("Channel %d is invalid on a Raspberry Pi in BCM mode." % (channel,))
            return channel
        if self.mode == self.BOARD:
            try:
                num = self.PIN_TO_GPIO[channel]
            except IndexError:
                num = -1
            if num == -1:
                raise ValueError("Channel %d is invalid on a Raspberry Pi in BOARD mode." % (channel,))
            return num

        raise RuntimeError("Please set pin numbering mode using GPIO.setmode(GPIO.BOARD) or GPIO.setmode(GPIO.BCM)")

    def _event_cleanup(self, gpio):
        with self._watcher_lock:
            self._detected_events.discard(gpio)
            self._watched_gpios.pop(gpio, None)

    def __del__(self):
        if not self._mapfile is None:
            self._mapfile.close()            

    # ---- [ Official GPIO - API ] -------------------------------------------------------

    def setup(self, channel, direction, pull_up_down = PUD_OFF, initial = None):
        if isinstance(channel, int):
            channel = [channel,]
        elif not isinstance(channel, (list, tuple)):
            raise ValueError("Channel must be an integer or list/tuple of integers")

        if direction == self.OUT:
            if pull_up_down != self.PUD_OFF:
                raise ValueError("pull_up_down parameter is not valid for outputs.")
        elif direction == self.IN:
            if initial != None:
                raise ValueError("initial parameter is not valid for inputs.")
            if pull_up_down not in (self.PUD_OFF, self.PUD_DOWN, self.PUD_UP):
                ValueError("Invalid value %r for pull_up_down - should be either PUD_OFF, PUD_UP or PUD_DOWN" % (pull_up_down,))
        else:
            raise ValueError("An invalid direction %r was passed to setup()" % (direction,))

        for ch in channel:
            if not isinstance(ch, int):
                raise ValueError("Channel must be an integer (got %r instead)" % (ch,))
            gpio = self._get_gpio_number(ch)
            self._setup_one(gpio, direction, pull_up_down, initial)

    def cleanup(self, channel = None):
        if channel is None:
            self.event_cleanup_all()
            for ch in self.PIN_TO_GPIO:
                if ch == -1:
                    continue
                self._setup_gpio(ch, self.IN, self.PUD_OFF)
            self.mode = self.MODE_UNKNOWN
            return

        if isinstance(channel, int):
            channel = [channel,]
        elif not isinstance(channel, (list, tuple)):
            raise ValueError("Channel must be an integer or list/tuple of integers")

        for ch in channel:
            if not isinstance(ch, int):
                raise ValueError("Channel must be an integer")
            gpio = self._get_gpio_number(ch)
            self._cleanup_one(gpio)

    def setwarnings(self, what):
        self._warnings = bool(what)

    def setmode(self, mode):
        if (self.mode != self.MODE_UNKNOWN) and (mode != self.mode):
            raise ValueError("A different mode has already been set!")
        if mode not in (self.BOARD, self.BCM):
            raise RuntimeError("An invalid mode (%s) was passed to setmode()" % (mode,))
        self.mode = mode

    def getmode(self):
        return self.mode

    def output(self, channel, value):
        if isinstance(channel, int):
            channel = [channel,]
        elif not isinstance(channel, (list, tuple)):
            raise ValueError("Channel must be an integer or list/tuple of integers")

        if isinstance(value, int):
            value = [value,]
        elif not isinstance(channel, (list, tuple)):
            raise ValueError("Value must be an integer or list/tuple of integers")

        if len(value) != len(channel):
            raise RuntimeError("Number of channels != number of values")

        for i, ch in enumerate(channel):
            v = value[i]
            if not isinstance(v, int):
                raise ValueError("Value must be an integer or boolean")
            if not isinstance(ch, int):
                raise ValueError("Channel must be an integer")
            self._output_one(ch, v)

    def input(self, channel):
        gpio = self._get_gpio_number(channel)
        if not self._read_direction(gpio) in (self.IN, self.OUT):
            raise RuntimeError("You must setup() the GPIO channel first")
        return self._read_value(gpio)

    def __call__(self):
        while not self._watcher_shutdown:
            with self._watcher_lock:
                watched = self._watched_gpios.copy()
            detected = {}
            for gpio, (last_value, _, callbacks) in watched.items():
                if self._watcher_shutdown:
                    return
                current_value = self._read_value(gpio)
                if last_value != current_value:
                    detected[gpio] = current_value
                    channel = self._get_channel_number(gpio)
                    for callback in callbacks:
                        if self._watcher_shutdown:
                            return
                        try:
                            callback(channel)
                        except Exception:
                            traceback.print_exc()
            if self._watcher_shutdown:
                return

            if detected:
                with self._watcher_lock:
                    self._detected_events.update(detected)
                    for gpio, current_value in detected.items():
                        (_, edge, callbacks) = self._watched_gpios[gpio]
                        self._watched_gpios[gpio] = (current_value, edge, callbacks)
                continue

            with self._watcher_lock:
                self._watcher_condition.wait(0.05)

    def add_event_detect(self, channel, edge, callback = None, bouncetime = None):
        if not callback is None and (not callable(callback)):
            raise TypeError("callback has to be a callable!")
        gpio = self._get_gpio_number(channel)
        direction = self._read_direction(gpio)
        if direction != self.IN:
            raise RuntimeError("You must setup() the GPIO channel as input first!")
        if not edge in (self.RISING, self.FALLING, self.BOTH):
            raise ValueError("The edge must be set to RISING, FALLING or BOTH!")
        if bouncetime != None and bouncetime < 0:
            raise ValueError("Bouncetime has to be greater than 0!")

        with self._watcher_lock:
            if not gpio in self._watched_gpios:
                lv = self._read_value(gpio)
                self._watched_gpios[gpio] = (lv, edge, {callback})
            else:
                lv, stored_edge, callbacks = self._watched_gpios[gpio]
                if stored_edge != edge:
                    raise RuntimeError("Conflicting edge detection already enabled for this GPIO channel") 
                callbacks.add(callback)
                self._watched_gpios[gpio] = (lv, stored_edge, callbacks)
            self._watcher_condition.notify()

    def remove_event_detect(self, channel):
        gpio = self._get_gpio_number(channel)
        with self._watcher_lock:
            self._watched_gpios.pop(gpio, None)

    def event_detected(self, channel):
        gpio = self._get_gpio_number(channel)
        with self._watcher_lock:
            result = gpio in self._detected_events
            if result:
                self._detected_events.discard(gpio)
        return result

    def event_cleanup_all(self):
        with self._watcher_lock:
            self._detected_events.clear()
            self._watched_gpios.clear()

    # ---- [ Test API ] -------------------------------------------------------

    def set_mapfile(self, mapfile, initialize: bool = False):
        """
        Set a mapfile for possibly sharing between processes.
        Args:
            - mapfile: This can be either a path to a writable physical
                file or a fileno of an already opened file (mode 'r+b')
            - initialize (bool): Set to `True` for cleaning up the file
                initialize it's content. Initialize means to set the
                directions to 255 (neither `IN` nor `OUT`), set all
                `PIN` values to `LOW` and all resistors to `PUD_OFF`.
        """
        created = True
        if not self._mapfile is None:
            self._mapfile.close()
        self._mmap = None
        if isinstance(mapfile, (pathlib.Path, str)):
            p = pathlib.Path(mapfile)
            if p.exists():
                created = False
            else:
                with p.open("wb") as f:
                    f.write(b'000' * 53)
            self._mapfile = p.open("r+b")
            fileno = self._mapfile.fileno()
        else:
            self._mapfile = None
            fileno = mapfile

        self._mmap = mmap.mmap(fileno, 53 * 3)

        if initialize or created:
            for i in range(53):
                self._mmap[self.DIRECTION_OFFSET + i] = 255
                self._mmap[self.PUD_OFFSET + i] = GPIODummy.PUD_OFF
                self._mmap[self.VALUE_OFFSET + i] = GPIODummy.LOW
            self._flush()

        return created

    def allow_write(self, allow = True):
        """
        Sets the write mode depending on `allow`.
        If `True` all PINs are writeable (output)
        independent of their state without getting an exception.
        """
        self._write_allowed = allow

    def write_context(self):
        """
        Returns a context in which writing to all PINs is
        possible.
        See also allow_write.
        """
        return GPIO._allow_write(self)

    class _allow_write(object):
        def __init__(self, gpioinst):
            self._gpio = gpioinst
            self._previous = False
        def __enter__(self):
            self._previous = self._gpio._write_allowed
            self._gpio._write_allowed = True
        def __exit__(self, *_):
            self._gpio._write_allowed = self._previous


GPIO = GPIODummy()