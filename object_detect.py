#!/usr/bin/env python3

# Copyright (c) FIRST and other WPILib contributors.
# Open Source Software; you can modify and/or share it under the terms of
# the WPILib BSD license file in the root directory of this project.

import json
import sys
import time

import cv2
import numpy as np
from cscore import CameraServer, UsbCamera, VideoSource
from networktables import NetworkTables, NetworkTablesInstance

#   JSON format:
#   {
#       "team": <team number>,
#       "ntmode": <"client" or "server", "client" if unspecified>
#       "cameras": [
#           {
#               "name": <camera name>
#               "path": <path, e.g. "/dev/video0">
#               "pixel format": <"MJPEG", "YUYV", etc>   // optional
#               "width": <video mode width>              // optional
#               "height": <video mode height>            // optional
#               "fps": <video mode fps>                  // optional
#               "brightness": <percentage brightness>    // optional
#               "white balance": <"auto", "hold", value> // optional
#               "exposure": <"auto", "hold", value>      // optional
#               "properties": [                          // optional
#                   {
#                       "name": <property name>
#                       "value": <property value>
#                   }
#               ],
#               "stream": {                              // optional
#                   "properties": [
#                       {
#                           "name": <stream property name>
#                           "value": <stream property value>
#                       }
#                   ]
#               }
#           }
#       ]
#       "switched cameras": [
#           {
#               "name": <virtual camera name>
#               "key": <network table key used for selection>
#               // if NT value is a string, it's treated as a name
#               // if NT value is a double, it's treated as an integer index
#           }
#       ]
#   }

# /boot/frc.json is where the Romi web interface saves the camera definition file.
configFile = "/boot/frc.json"

class CameraConfig: pass

team = None
server = False
cameraConfigs = []
switchedCameraConfigs = []
cameras = []

def parseError(str):
    """Report parse error."""
    print("config error in '" + configFile + "': " + str, file=sys.stderr)

def readCameraConfig(config):
    """Read single camera configuration."""
    cam = CameraConfig()

    # name
    try:
        cam.name = config["name"]
    except KeyError:
        parseError("could not read camera name")
        return False

    # path
    try:
        cam.path = config["path"]
    except KeyError:
        parseError("camera '{}': could not read path".format(cam.name))
        return False

    # stream properties
    cam.streamConfig = config.get("stream")

    cam.config = config

    cameraConfigs.append(cam)
    return True

def readSwitchedCameraConfig(config):
    """Read single switched camera configuration."""
    cam = CameraConfig()

    # name
    try:
        cam.name = config["name"]
    except KeyError:
        parseError("could not read switched camera name")
        return False

    # path
    try:
        cam.key = config["key"]
    except KeyError:
        parseError("switched camera '{}': could not read key".format(cam.name))
        return False

    switchedCameraConfigs.append(cam)
    return True

def readConfig():
    """Read configuration file."""
    global team
    global server

    # parse file
    try:
        with open(configFile, "rt", encoding="utf-8") as f:
            j = json.load(f)
    except OSError as err:
        print("could not open '{}': {}".format(configFile, err), file=sys.stderr)
        return False

    # top level must be an object
    if not isinstance(j, dict):
        parseError("must be JSON object")
        return False

    # team number
    try:
        team = j["team"]
    except KeyError:
        parseError("could not read team number")
        return False

    # ntmode (optional)
    if "ntmode" in j:
        str = j["ntmode"]
        if str.lower() == "client":
            server = False
        elif str.lower() == "server":
            server = True
        else:
            parseError("could not understand ntmode value '{}'".format(str))

    # cameras
    try:
        cameras = j["cameras"]
    except KeyError:
        parseError("could not read cameras")
        return False
    for camera in cameras:
        if not readCameraConfig(camera):
            return False

    # switched cameras
    if "switched cameras" in j:
        for camera in j["switched cameras"]:
            if not readSwitchedCameraConfig(camera):
                return False

    return True

def startCamera(config):
    """Start running the camera."""
    print("Starting camera '{}' on {}".format(config.name, config.path))
    inst = CameraServer.getInstance()
    camera = UsbCamera(config.name, config.path)
    server = inst.startAutomaticCapture(camera=camera, return_server=True)

    camera.setConfigJson(json.dumps(config.config))
    camera.setConnectionStrategy(VideoSource.ConnectionStrategy.kKeepOpen)

    if config.streamConfig is not None:
        server.setConfigJson(json.dumps(config.streamConfig))

    return camera

def startSwitchedCamera(config):
    """Start running the switched camera."""
    print("Starting switched camera '{}' on {}".format(config.name, config.key))
    server = CameraServer.getInstance().addSwitchedCamera(config.name)

    def listener(fromobj, key, value, isNew):
        if isinstance(value, float):
            i = int(value)
            if i >= 0 and i < len(cameras):
              server.setSource(cameras[i])
        elif isinstance(value, str):
            for i in range(len(cameraConfigs)):
                if value == cameraConfigs[i].name:
                    server.setSource(cameras[i])
                    break

    NetworkTablesInstance.getDefault().getEntry(config.key).addListener(
        listener,
        NetworkTablesInstance.NotifyFlags.IMMEDIATE |
        NetworkTablesInstance.NotifyFlags.NEW |
        NetworkTablesInstance.NotifyFlags.UPDATE)

    return server

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        configFile = sys.argv[1]

    # read configuration
    if not readConfig():
        sys.exit(1)

    # start NetworkTables
    ntinst = NetworkTablesInstance.getDefault()
    if server:
        print("Setting up NetworkTables server")
        ntinst.startServer()
    else:
        print("Setting up NetworkTables client for team {}".format(team))
        ntinst.startClientTeam(team)
        ntinst.startDSClient()

    vision_nt = NetworkTables.getTable("Vision")

    # start cameras
    for config in cameraConfigs:
        cameras.append(startCamera(config))

    # start switched cameras
    for config in switchedCameraConfigs:
        startSwitchedCamera(config)

    #######################################################################
    #                                                                     #
    # Add code for image processing here                                  #
    #                                                                     #
    #######################################################################

    # Get the Camera Server
    server = CameraServer.getInstance()
    
    # Open the input video stream from the server
    input_stream = server.getVideo()
    
    # Get the dimensions of the camera image
    cfg = cameraConfigs[0].config
    height = cfg['height']
    width = cfg['width']
    print(f'Image Size: {width} x {height} @ {cfg["fps"]} fps')

    # Create an output video stream for the processed video
    output_stream = server.putVideo("Processed", width, height)

    # Create a buffer for reading a frame of the input stream
    img = np.zeros(shape=(height, width, 3), dtype=np.uint8)

    # loop forever    
    while True:
        start_time = time.time()  # for tracking the frame rate

        frame_time, input_img = input_stream.grabFrame(img)

        if frame_time == 0:
            output_stream.notifyError(input_stream.getError())
            continue

        # Create a copy of the input image for marking up as the output.
        output_img = np.copy(input_img)

        # Convert the input image to HSV (hue, saturation, value).
        # HSV is often used in image processing since hue represents to color.
        hsv_img = cv2.cvtColor(input_img, cv2.COLOR_BGR2HSV)

        # Convert to a binary (black & white) image based on HSV color.
        binary_img = cv2.inRange(hsv_img, (0, 96, 112), (35, 255, 255))

        # Apply morphological operation to "clean up" the binary image.
        # You can create an output stream for the binary image to see how
        # these operations change the binary image.
        kernel = np.ones((3, 3), np.uint8)
        binary_img = cv2.morphologyEx(binary_img, cv2.MORPH_CLOSE, kernel)
        binary_img = cv2.erode(binary_img, kernel, iterations = 1)

        # Detect the outlines (contours) of the white regions of the binary image.
        contours, _ = cv2.findContours(binary_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Display the contours on the output image.
        cv2.drawContours(output_img, contours, -1, (0, 255, 0), 2)

        # Here is where you will add additional processing to identify the correct contour (if 
        # there is more than one) for the object you want to identify and to get the object's
        # location in the field of view of the camera. 

        processing_time = time.time() - start_time
        fps = 1 / processing_time

        # Once you have that information, you can output it to NetworksTables, so that it is 
        # availablle to your Robot code. 
        vision_nt.putNumber("Frame Rate (fps)", fps)
        vision_nt.putNumberArray("Center Color", hsv_img[60, 80])

        # You will also want to send any processed video to your output stream(s) for display on
        # Shuffleboard.
        output_stream.putFrame(output_img)
