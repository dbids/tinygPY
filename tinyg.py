import serial
import serial.tools.list_ports as lp
import time
from datetime import datetime
import sys
import os
import traceback
import re
import math as m
import threading

# Define maximums
XMAX = 17.900
YMAX = 11.8
ZMAX = 6

# Thread sync lock
serial_lock = threading.Lock()
NotClosed = threading.Event()
MovementFinished = threading.Event()
ThreadException = threading.Event()

# Hard Reset Exception Class Definition
class TinygThreadException(Exception):
  pass

## Implement tinyg thread
class TinygThread(threading.Thread):
  def run(self):
    self.exc = None
    try:
      self.ret = self._target(*self._args, **self._kwargs)
    except BaseException as e:
      self.exc = e

  def join(self, timeout=None):
    super(TinygThread, self).join(timeout)
    if self.exc:
      raise self.exc
    return self.ret

## Implement tinyg library object
class tinyg_obj():

  ## Initialize class and its parameters
  def __init__(self):
    self.r_th = None
    self.ser = None
    self.vid = "VID:PID=0403:6015"
  # =================================================================================
  # Serial Connection
  # =================================================================================

  ## Find the port on windows for the TinyG
  ## If the port is not found a ConnectionError is raised, which should be caught in the control function,
  ## and the connection setup manually by the user.
  ## credit : http://arduino-er.blogspot.com/2015/04/python-auto-detect-arduino-connect.html
  def FindTinyGPort(self):
    portList = list(lp.comports())
    for port in portList:
      if self.vid in port[0]\
        or self.vid in port[1]\
        or self.vid in port[2]:
        return port[0]
    assert ConnectionError

  ## Sets up and returns a handle to the serial connection for the TinyG
  ## Also configures RTS/CTS flow control on both ends
  def SetupConnection(self, manualPort="auto",verbose=True):
    self.ser = serial.Serial()
    self.ser.baudrate = 115200
    self.ser.port = self.FindTinyGPort() if(manualPort == "auto") else manualPort
    self.ser.open()
    assert(self.ser.is_open)
    self.ser.flushInput()
    self.ser.flushOutput()
    NotClosed.set()

    ## Remove logs
    try:
      os.remove("tinyg.log")
    except:
      pass

    ## Configure connection specific settings
    self.WriteString("{\"ex\", 2}") ## Add RTS/CTS to the link
    self.ser.rtscts = True
    self.WriteString("{\"sr\", 0}") ## turns off status report
    time.sleep(1)
    self.ReadString(p=True)

    ## Start reading thread (daemon will run in background and stop when prog stops)
    ThreadException.clear()
    self.r_th = TinygThread(target=self.ReadThread, args=("./tinyg.log", verbose))
    self.r_th.start()

    ## Turn off the Solenoid
    self.SolenoidOff()

  ## Closes the passed serial conenction
  def CloseConnection(self):
    self.SolenoidOff()
    try:
      ## Clean up reading thread
      NotClosed.clear()
      if(self.r_th is not None):
        self.r_th.join(timeout=60)

    except Exception as e:
      ## Issue a serial command that clears the hard reset
      self.SoftwareHardReset()
      print(e)
      pass

    finally:
      ## Close serial connection
      print("Closing serial connection")
      self.ser.close()


  # =================================================================================
  # Read / Write
  # =================================================================================

  ## Write a string to TinyG and print+log that string
  def WriteString(self, input:str, logPath = "./tinyg.log"):
    try:
      assert(self.ser.is_open)
      if not(input.endswith('\n')):
        input += "\n"
      b = input.encode('utf-8')
      self.ser.flush()
      bytesWritten = self.ser.write(b)

      currtime = datetime.now().strftime("%Y%D:%H:%M:%S")
      before = "\n________________________________________\n"+str(currtime)+"\nINPUT:\n"
      print(before + input)
      with open(logPath,'a') as f:
        f.write(before + input)

    except Exception as e:
      print("\n..............................SERIAL WRITE EXCEPTION...................................")
      ex_type, ex_value, ex_traceback = sys.exc_info()
      trace_back = traceback.extract_tb(ex_traceback)
      stack_trace = list()
      for trace in trace_back:
        stack_trace.append("File : %s , Line : %d, Func.Name : %s, Message : %s" % (trace[0], trace[1], trace[2], trace[3]))
      print("Exception type : %s " % ex_type.__name__)
      print("Exception message : %s" %ex_value)
      print("Stack trace : %s" %stack_trace)
      raise TinygThreadException(ex_value)

  ## Read a string from TinyG and print+log that string
  def ReadString(self, logPath = "./tinyg.log",p = False):
    line=""
    try:
      currtime = datetime.now().strftime("%Y%D:%H:%M:%S")
      prelude = "\n________________________________________\n"+str(currtime)+"\nOUTPUT:\n"
      out=""

      ## Read
      while(self.ser.in_waiting > 0):
        line = self.ser.read_until(size=9999)
        try:
          out += line.decode('utf-8')
        except UnicodeError:
          print("\n..............................UNICODE ERROR DETECTED...................................")
          print(line)
          continue

        ## Check for hard reset status report here
        ## {"er":{"fb":440.20,"st":204,"msg":"Limit switch hit - Shutdown occurred"}}
        pattern = re.compile(r"\\{\"er\":\\{-[a-zA-Z]+\"[^\"]*\"st\":204,\"[a-zA-Z]+\":\"(?:[^\"]|\"\")*\"\\}\\}")
        if (bool(re.match(pattern, line.decode('utf-8')))):
          raise TinygThreadException(line.decode('utf-8'))

      ## Print and write to log file
      if(p):
        print(prelude+out)
      with open(logPath,'a') as f:
        f.write(prelude+out)

      self.ser.flush()

    except TinygThreadException:
      # reraise the exception to avoid the exception handler below in the case of hard resets
      print("\n..............................HARD RESET DETECTED...................................")
      ThreadException.set()
      MovementFinished.set()
      raise

    except Exception as e:
      print("\n..............................SERIAL READ EXCEPTION...................................")
      ex_type, ex_value, ex_traceback = sys.exc_info()
      trace_back = traceback.extract_tb(ex_traceback)
      stack_trace = list()
      for trace in trace_back:
        stack_trace.append("File : %s , Line : %d, Func.Name : %s, Message : %s" % (trace[0], trace[1], trace[2], trace[3]))
      print("Exception type : %s " % ex_type.__name__)
      print("Exception message : %s" %ex_value)
      print("Stack trace : %s" %stack_trace)
      ThreadException.set()
      MovementFinished.set()
      raise TinygThreadException(ex_value)

    return out

  def ReadThread(self, logPath = "./tinyg.log", p = False):
    ## Define a local movement timeout counter which counts the number of empty loops
    readdata = threading.local()
    readdata.mtc = 0
    readdata.max_count = 3             #TODO: Adjust as needed
    readdata.time_between_loops = 0.1  #TODO: Adjust as needed

    while(NotClosed.is_set() and not ThreadException.is_set()):
      if(self.ser.in_waiting):
        readdata.mtc = 0

        ## Block waiting for the serial channel to be available from the reader
        serial_lock.acquire()

        if(self.ser.in_waiting):
          self.ReadString(logPath=logPath, p=p)

        ## Release the serial lock
        serial_lock.release()

      ## Increment the sleep counter.
      ## If it exceeds the max then condtionally set MovementFinished to allow next write.
      readdata.mtc += 1
      if(readdata.mtc > readdata.max_count and not(MovementFinished.is_set())):
        readdata.mtc = 0
        MovementFinished.set()

      ## Sleep a configurable amount between loops
      time.sleep(readdata.time_between_loops)

  ## Implement writing with the read thread
  def WriteThread(self, inStr, logPath = "./tinyg.log"):
    ## Block waiting for the serial channel to be available from the reader
    serial_lock.acquire()

    ## Write string
    self.WriteString(inStr, logPath=logPath)

    ## Release the serial lock
    serial_lock.release()
    time.sleep(0.01)  #TODO: Adjust as needed

  ## Wrapper that creates a writing thread and waits for it to finish
  def WriteThreadWrapper(self, inStr, logPath = "./tinyg.log"):
    if not ThreadException.is_set():
      try:
        MovementFinished.clear()
        w_th = TinygThread(target=self.WriteThread, args=(inStr, logPath))
        w_th.start()
        w_th.join()
        MovementFinished.wait()
        if ThreadException.is_set():
          raise TinygThreadException
      except:
        raise TinygThreadException
    else:
      raise TinygThreadException

  # =================================================================================
  # Configuration
  # =================================================================================

  def SetConfig(self, startingdir,ConfigFile= "tinyg_basic_config.json", compareList=[999]):
    f = open(startingdir+ConfigFile)
    lines = f.readlines()
    for value, line in enumerate(lines):
      if((compareList[0] == 999) or (value in compareList)):
        self.WriteThreadWrapper(str(line))
    f.close()

  ## Compares read config information to the expected and returns True if they match
  def CheckConfig(self, startingdir,ConfigFile= "tinyg_basic_config.json"):

    try:
      ## Take serial communication lock
      serial_lock.acquire()

      ## Get config info from our config JSON file and convert to string with n instead of value
      ## At the same time create a dictionary from the file
      print("readFile:",startingdir+ConfigFile)
      f = open(startingdir+ConfigFile)
      lines = f.readlines()
      f.close()
      checkConfString = ""
      confDict = {}
      currKey = ""
      currValue = ""
      for currString in lines:
        ## Create dict
        currStringList = re.split('{|:|"|}',currString)
        currKey = str(currStringList[2]).lower()
        currValue = float(currStringList[4])
        confDict[currKey] = currValue
        ## Convert to long string
        l = currString.split(":")
        l[1]="n}"
        currString = ":".join(l)
        checkConfString += currString + '\n'
      
      ## Send resquest for config info from TinyG
      self.WriteString(checkConfString)
 
      compareList = []
      while(True):

        ## Get config info from TinyG
        time.sleep(0.5)
        tinygConfString = self.ReadString(p=True)

        ## Check for no string found
        if (len(tinygConfString) == 0):
          continue

        ## Convert to many strings
        tinygConfStrings = tinygConfString.split('\n')

        ## Iterate through response strings checking for responses
        ## {"r":{"ej":1}, "f":[1,0,9,2005]}
        ## \{"r":\{"ej":([+-]?(?=\.\d|\d)(?:\d+)?(?:\.?\d*))(?:[eE]([+-]?\d+))?\},"f":\[[0-9]+,[0-9]+,[0-9]+,[0-9]+\]\}
        for respString in tinygConfStrings:

          ## Iterate through all configuration settings, looking for regex match
          for value, key in enumerate(confDict):
            ## Generate regex for given confString
            patternString = "\\{\"r\":\\{\"" + key + "\":([+-]?(?=\\.\\d|\\d)(?:\\d+)?(?:\\.?\\d*))(?:[eE]([+-]?\\d+))?\\},\"f\":\\[[0-9]+,[0-9]+,[0-9]+,[0-9]+\\]\\}"
            pattern = re.compile(patternString)
            
            ## If found
            if (bool(re.match(pattern, respString))):

              ## Convert string to dictionary
              currStringList = re.split('{|:|"|}',respString)
              tinygDict = {}
              if(str(currStringList[2]) == "r"):
                currKey = str(currStringList[6]).lower()
                currValue = float(currStringList[8])
                tinygDict[currKey] = currValue

              ## Do value comparison, and if incorrect append to compare list
              if (tinygDict[key] != confDict[key]) :
                compareList.append(value)

              ## Remove from dict as response found
              confDict.pop(key)
              break
        
        ## Check if we have found all the responses
        if(len(confDict.keys()) == 0):
          break

      # Release serial lock
      serial_lock.release()

    except:
      serial_lock.release()
      raise
    
    return compareList

  ## Wrapper function to implement configuration of TinyG
  def Config(self, startingdir,ConfigFile= "tinyg_basic_config.json"):

    ## Get current config information
    compareList = self.CheckConfig(startingdir, ConfigFile)

    ## If there are config options to change, change them
    while (len(compareList)):
      self.SetConfig(startingdir, ConfigFile, compareList)
      compareList = self.CheckConfig(startingdir, ConfigFile)
    return

  # =================================================================================
  # Define Axes (Homing procedure)
  # =================================================================================

  # Unsets the given axis as homed
  # SPEC ON COMMAND:
  #   Homes all axes present in command. At least one axis must be specified
  def HomeAxis(self, X, Y, Z, A):
    Command = "{\"gc\":\"G28.2"
    if X==1:
      Command = Command + " X0"
    if Y==1:
      Command = Command + " Y0"
    if Z==1:
      Command = Command + " Z0"
    if A==1:
      Command = Command + " A0"
    self.WriteThreadWrapper(Command + "\"}")

  # Home all axes based on above command
  def Home(self):
    self.HomeAxis(0, 0, 1, 0)
    self.HomeAxis(1, 0, 0, 0)
    self.HomeAxis(0, 1, 0, 0)

  # Resets the defined coordinate of the machine using the G28.3 command.  Use if can't be homed
  # SPEC ON COMMAND:
  #   Set axis to zero or other value. Use to zero axes that cannot otherwise be homed
  def SetPosition(self, X, Y, Z, A):
    Command = "{\"gc\":\"G28.3"
    if X is not None:
      Command = Command + " X" + str(X)
    if Y is not None:
      Command = Command + " Y" + str(Y)
    if Z is not None:
      Command = Command + " Z" + str(Z)
    if A is not None:
      Command = Command + " A" + str(A)
    self.WriteThreadWrapper(Command + "\"}")

  # =================================================================================
  # Save points
  # =================================================================================

  # Saves the absolute position to Pos1.  Can be returned to using GoPos1 regardless
  # of coordinate system.
  # SPEC ON COMMAND:
  #   The current machine position is recorded (No parameters are provided)
  def SavePos1(self):
    self.WriteThreadWrapper("{\"gc\":\"G28.1\"}")

  # Same as SavePos1 for Pos2
  def SavePos2(self):
    self.WriteThreadWrapper("{\"gc\":\"G30.1\"}")

  # Returns to the absolute position saved with SavePos1.
  # SPEC ON COMMAND:
  #   Go to G28.1 position. Optional axes specify an intermediate point(not implemented here)
  def GoPos1(self):
    self.WriteThreadWrapper("{\"gc\":\"G28\"}")

  # Returns to the absolute position saved with SavePos2.
  def GoPos2(self):
    self.WriteThreadWrapper("{\"gc\":\"G30\"}")

  # =================================================================================
  # Movement
  # =================================================================================

  # Jog the movement of any of the axis
  def Jog(self, Speed, X, Y, Z, A):
    if X is not None and Y is not None:
      self.WriteThreadWrapper("{\"gc\":\"G1 F" + str(Speed) + " X" + str(X) + " Y" + str(Y) + "\"}")
    elif X is not None:
      self.WriteThreadWrapper("{\"gc\":\"G1 F" + str(Speed) + " X" + str(X) + "\"}")
    elif Y is not None:
      self.WriteThreadWrapper("{\"gc\":\"G1 F" + str(Speed) + " Y" + str(Y) + "\"}")
    elif Z is not None:
      self.WriteThreadWrapper("{\"gc\":\"G1 F" + str(Speed) + " Z" + str(Z) + "\"}")
    elif A is not None:
      self.WriteThreadWrapper("{\"gc\":\"G1 F" + str(Speed) + " A" + str(A) + "\"}")
    else:
      print("***Jog, no axis")

  # % symbol is used in GCode to start/end a new file, so cancels jog in progress
  def CancelJog(self):
    self.WriteThreadWrapper("!%")

  # Linear move along X, Y, and/or A axes to the specified point at a specified feed rate
  # feed rate ~= speed
  # SPEC ON COMMAND:
  #   Feed at feed rate F. At least one axis must be present.
  def MoveLinear(self, Speed, X, Y, Z, A):
    Command = "{\"gc\":\"G1 F"
    Command = Command + str(Speed) + " "
    if X is not None:
      Command = Command + " X" + str(X)
    if Y is not None:
      Command = Command + " Y" + str(Y)
    if Z is not None:
      Command = Command + " Z" + str(Z)
    if A is not None:
      Command = Command + " A" + str(A)
    self.WriteThreadWrapper(Command + "\"}")

  # Rapid move along X, Y, and/or A axes to the specified point
  # SPEC ON COMMAND:
  #   Traverse at maximum velocity. At least one axis must be present.
  def MoveRapid(self, X, Y, Z, A):
    Command = "{\"gc\":\"G0"
    if X is not None:
      if(int(X)<0): X = str(0)
      if(int(X)>XMAX): X = str(XMAX)
      Command = Command + " X" + str(X)
    if Y is not None:
      if(int(Y)<0): Y = str(0)
      if(int(Y)>YMAX): Y = str(YMAX)
      Command = Command + " Y" + str(Y)
    if Z is not None:
      if(int(Z)<0): Z = str(0)
      if(int(Z)>ZMAX): Z = str(ZMAX)
      Command = Command + " Z" + str(Z)
    if A is not None:
      if(int(A)<0): A = str(0)
      Command = Command + " A" + str(A)
    self.WriteThreadWrapper(Command + "\"}")

  ## Turn on and off the spindle pin
  def SpindleOff(self):
    self.WriteThreadWrapper("{\"gc\":\"M05\"}")

  def SpindleOn(self):
    self.WriteThreadWrapper("{\"gc\":\"M03\"}")

  # =================================================================================
  # Get Position
  # =================================================================================

  def GetCurrPos(self):
    serial_lock.acquire()
    self.WriteString("{\"gc\":\"M114\"}")
    time.sleep(0.1)
    posString = self.ReadString(p=True)
    serial_lock.release
    return posString

  # =================================================================================
  # Reset
  # =================================================================================
  # The system can only be recovered by hitting RESET, sending (control X in ASCII) to the serial port, or power cycling.
  def SoftwareHardReset(self):
    self.ser.flushInput()
    self.ser.flushOutput()
    self.WriteString(str(chr(24)))
