# tinygPY
TinyG Motor Control in Python.  Originally used for an undergraduate capstone project.  The functionality is far from complete and pull requests are more than welcome.

# Code description:

## Communication Setup
The first step is to get a consistent and efficient communication setup with the TinyG. Communication is done over a USB cable, and we used the PySerial library in python to facilitate communication. 
* `SetupConnection` opens the serial connection, automatically finding the TinyG board out of the list of available serial ports if the serial port us unsepcified using the TinyG’s GPID in FindTinyGPort.  The source code would need to be changed to work for your own boards GPID.
* There is also a function called `CloseConnection` which closes the serial connection safely, killing any running threads.

## Reading and Writing
The `ReadString` and `WriteString` functions send signals to the board and reads the responses back from the board respectively. Reading is threaded so that it occurs continuously, but at the same time would indicate when we could safely write. This allows for a latency insensitive design w.r.t our communication and greatly improves the speed at which we can  move the machine. This is facilitated by the `ReadThread` and `WriteThread` functions.

## Configuration
Next, to use the TinyG effectively, there are over a hundred parameters that must be considered and configured to move the board. Tuning these parameters takes time. There are a few functions which together query the board for its current configuration information (`CheckConfig`) at the start of a run of the machine, and if any parameters are not what is desired based on a JSON file, then we set them accordingly (`SetConfig`), and query the board again to double-check that they have been set. This is all facilitated by the `Config` function.
* _Note_: These functions rely on strict JSON formatting for the TinyG and no status reports, so leave these settings as is in the configuration file.

## Homing
Homing is the process wherein the machine moves along each axis until it hits one of its two limit switches on that axis. After it hits the switch, it backs off the desired amount (such that the switch is not depressed) and defines that as a zero point along that axis. Outside of homing the two limit switches on each axis are used to stop the machine before it exceeds its bounds. Getting the machine home consistently took time but was a necessary step to ensure that we have consistent coordinates. `Home` homes all axes in the desired order, but homing of a single axis can be done with the `HomeAxis` command. In addition, `SetPosition` does not move the machine, but sets the coordinate of the specified axes to 0 at its current position, useful for rotating axes but not really for us.

Finally, once all these setup functions were complete, a small library of functions needed to be written which given some inputs constructed and sent G-code commands over the serial connection.

* `SavePos1`, `SavePos2`, `GoPos1`, `GoPos2` save a position and return to a saved position respectively.
* `Jog` moves the machine a small amount using a linear move command and `CancelJog` cancels that move (Warning: not tested).
* `MoveLinear` moves at a given speed (feed rate) to the absolute coordinates it takes as input. Note that coordinates need to be converted from mm to units the tinyg uses, for which the conversion factors are in config_distance.yml.
* `MoveRapid` moves at the maximum speed on all specified axes to the absolute coordinates it takes as input. Note that coordinates need to be converted from mm to units the tinyg uses, for which the conversion factors are in config_distance.yml.
* `SolenoidOn` and `SolenoidOff` turn on an off the pump output, switching the solenoid on or off on the relay.
* `GetCurrPos` queries the machine for its current coordinates (at least what the tinyg thinks are its coordinates) and returns them (Warning: not tested).
* `SoftwareHardReset` sends a signal to clear the error state on the TinyG board which is ASCII 0x24 or ctrl-x.
