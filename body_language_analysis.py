import numpy as np
import math as m


def calculate_distance_3d(wrist, mouth):
    """
    Calculate the Euclidean distance between wrist and mouth in three dimensions (x, y, z).

    Parameters:
        wrist (tuple): Tuple containing the x, y, and z coordinates of the wrist.
        mouth (tuple): Tuple containing the x, y, and z coordinates of the mouth.

    Returns:
        float: Euclidean distance between the wrist and mouth.
    """
    
    wrist = np.array(wrist)
    mouth = np.array(mouth)

    distance = np.linalg.norm(wrist - mouth)
    return distance

def calculate_angle(a,b,c):
    a = np.array(a) # First
    b = np.array(b) # Mid
    c = np.array(c) # End

    radians = np.arctan2(c[1]-b[1], c[0]-b[0]) - np.arctan2(a[1]-b[1], a[0]-b[0])
    angle = np.abs(radians*180.0/np.pi)

    if angle >180.0:
        angle = 360-angle

    return angle

def calculate_shoulder_knee_angle(shoulder, knee):
    """
    Calculate the angle between the shoulder and knee.

    Parameters:
        shoulder (list): Coordinates of the shoulder landmark [x, y].
        knee (list): Coordinates of the knee landmark [x, y].

    Returns:
        float: Angle between the shoulder and knee in degrees.
    """
    # Convert the coordinates to numpy arrays for easy computation
    shoulder = np.array(shoulder)
    knee = np.array(knee)

    # Compute the vector from shoulder to knee
    shoulder_to_knee_vector = knee - shoulder

    # Calculate the angle using arctan2
    angle_radians = np.arctan2(shoulder_to_knee_vector[1], shoulder_to_knee_vector[0])

    # Convert the angle from radians to degrees
    angle_degrees = np.degrees(angle_radians)

    # Ensure angle is positive
    if angle_degrees < 0:
        angle_degrees += 360

    return angle_degrees

def findDistance(x1, y1, x2, y2):
    dist = m.sqrt((x2-x1)**2+(y2-y1)**2)
    return dist
