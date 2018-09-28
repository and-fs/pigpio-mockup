# Raspberry Pi GPIO mockup

A platform independent RPi GPIO wrapper for testing and developing in any platform that runs Python 3.

How it works
---

In this lib the GPIO is implemented as a class which defines the RPI.GPIO API with the
difference that input / output is done in a memory mapped file (not to any real pins).

By using this technique it is possible to simulate different value on GPIO pins
to test the behaviour of your software when those pins are changing.
Not even in one process, be specifying a name for the memory mapped file
you can share this between different processes running in the same system.

Example 1 (in a single process)
---

```python
from gpio import GPIO

GPIO.setmode(GPIO.BOARD)    # setup to board numbering (as the header pins)
GPIO.setup(3, GPIO.IN)   # setup PIN 3 (GPIO #2) as input

value = GPIO.input(3)       # this will initially be 0
assert value == GPIO.LOW, "pin should be initially LOW!"

# now the testing part - change the pin value!
# using the write_mode context will allow you to output
# to an input pin (otherwise you will get an exception for writing
# to an input pin).
with GPIO.write_context():
    GPIO.output(3, GPIO.HIGH)
   
# now lets see what's happened
value = GPIO.input(3)
assert value == GPIO.HIGH, "pin should be HIGH now!"
```

Example 2 (sharing between processes)
---

### Watcher Script

Run the following script in a seperate command line (terminal) and look at its output.

```python
import time
from gpio import GPIO

# tell the GPIO to use a physical file 'gpio.m' for I/O and to initialize it.
GPIO.set_mapfile('gpio.m', initialize = True) 
GPIO.setmode(GPIO.BOARD)    # setup to board numbering (as the header pins)
GPIO.setup(3, GPIO.IN)   # use PIN3 for input

def OnPinEvent(channel):
    """This is called when PIN3 changes."""
    print ("PIN %d changed to %d" % (channel, GPIO.input(channel))

# now lets watch for changes on PIN 3
GPIO.add_event_detect(3, GPIO.BOTH, OnPinEvent)

print ("Script is running, press CTRL-C to exit.")
try:
    while True: # loop until Keyboard-Interrupt / SIGINT
        time.sleep(5)
except KeyboardInterrupt:
    print ("Bye, bye.")
```

### Commands

Now lets open another terminal to change the pins...

```python
from gpio import GPIO

# IMPORTANT! Use the same file here, but don't initialize it!
GPIO.set_mapfile('gpio.m') 
GPIO.setmode(GPIO.BOARD)    # setup to board numbering (as the header pins)

# because of using the same memory mapped file, PIN3 is already setup for input
# but let's change it's value and see what the upper script is telling:
with GPIO.write_context():     # important: use the write_context!
    GPIO.output(3, GPIO.HIGH)

with GPIO.write_context():     # important: use the write_context!
    GPIO.output(3, GPIO.LOW)

# and so on
```

# Using as a submodule

To easily use this project as a submodule, just tell git to check it out into your existing master.
For this open a terminal / command line in your project root and use the following:
```
git submodule add https://github.com/and-fs/pigpio-mockup.git gpio
```
This will check out pigpio-mockup into the gpio folder.
