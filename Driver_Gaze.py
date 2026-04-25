
# ============= Start to Remove Print Condition ====================

"""
Demonstration of the GazeTracking library.
Check the README.md for complete documentation.
"""

from GazeTracking import GazeTracking
import cv2
import os
import matplotlib.pyplot as plt
# from google.colab.patches import cv2_imshow
# # import cv2
# # from gaze_tracking import GazeTracking
# # Initialize the video capture

def track_gaze_module(video_path):
    
    left_count, right_count, up_count, down_count, middle_count, blinking_count,total_frames = 0,0,0,0,0,0,0
    # video_path = "/content/gdrive/MyDrive/Video Analyse Project/EyeMove_video.mp4"
    
    if not os.path.isfile(video_path):
        print("Error: File not found")
        return

    cap = cv2.VideoCapture(video_path)

    gaze = GazeTracking()
    # webcam = cv2.VideoCapture(0)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        total_frames += 1
        # Convert the frame to grayscale for facial landmark detection
        # gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # We send this frame to GazeTracking to analyze it
        gaze.refresh(frame)

        frame = gaze.annotated_frame()
        text = ""

        if gaze.is_blinking():
            text = "Blinking"
            blinking_count += 1
        elif gaze.is_right():
            text = "Looking right"
            right_count += 1
        elif gaze.is_left():
            text = "Looking left"
            left_count += 1
            # ===================
        elif gaze.is_up():
            text = "Looking Up"
            up_count +=1
        elif gaze.is_down():
            text = "Looking Down"
            down_count += 1
            # ===================
        elif gaze.is_center():
            text = "Looking center"
            middle_count += 1


    #  ========================== Gaze percentage ================================

        # Calculate gaze percentages
        left_percentage = (left_count / total_frames) * 100
        right_percentage = (right_count / total_frames) * 100
        up_percentage = (up_count / total_frames) * 100
        down_percentage = (down_count / total_frames) * 100
        middle_percentage = (middle_count / total_frames) * 100
        # blinking_percentage = (blinking_count / total_frames) * 100
        overall_gaze_percentage = (left_percentage + right_percentage + up_percentage + down_percentage + middle_percentage) / 5


    # ===========================  Show Text on each Frame =========================

        # cv2.putText(frame, text, (90, 60), cv2.FONT_HERSHEY_DUPLEX, 1.6, (147, 58, 31), 2)

        # left_pupil = gaze.pupil_left_coords()
        # right_pupil = gaze.pupil_right_coords()
        # cv2.putText(frame, "Left pupil:  " + str(left_pupil), (90, 130), cv2.FONT_HERSHEY_DUPLEX, 0.9, (147, 58, 31), 1)
        # cv2.putText(frame, "Right pupil: " + str(right_pupil), (90, 165), cv2.FONT_HERSHEY_DUPLEX, 0.9, (147, 58, 31), 1)
        # cv2.imshow('human',frame)

    # ==============================================================================

        # Display the gaze percentages
        # print("Left Percentage: {:.2f}%".format(left_percentage))
        # print("Right Percentage: {:.2f}%".format(right_percentage))
        # print("Up Percentage: {:.2f}%".format(up_percentage))
        # print("Down Percentage: {:.2f}%".format(down_percentage))
        # print("Middle Percentage: {:.2f}%".format(middle_percentage))
        # print("blinking Percentage: {:.2f}%".format(blinking_percentage))


        if cv2.waitKey(1) == 27:
            break

    # webcam.release()
    cv2.destroyAllWindows()
    
    
    # if middle_percentage >= 80:
    #     print("Good eye contact! --You are looking {:.2f}% in the middle.".format(middle_percentage))
    # else:
    #     print("Not good eye contact! because your focus in middle is not upto the mark as 80%,\n --Your gaze distribution is as follow:\n You are looking Left: {:.2f}%,\nYou are looking Right: {:.2f}%,\n You are looking Up: {:.2f}%,\n You are looking Down: {:.2f}%, \n You are looking Middle: {:.2f}%,\nYou are Blinking: {:.2f}".format(left_percentage, right_percentage, up_percentage, down_percentage, middle_percentage, blinking_percentage))

    #     print("\nGaze distribution Graph is as follow:\n\n")
    #     # Plot the gaze distribution
    #     labels = ['Left', 'Right', 'Up', 'Down', 'Middle', 'Blinking']
    #     percentages = [left_percentage, right_percentage, up_percentage, down_percentage, middle_percentage, blinking_percentage]
    #     plt.figure(figsize=(5,3))
    #     plt.bar(labels, percentages)
    #     plt.ylabel('Percentage')
    #     plt.title('Gaze Distribution')
    #     plt.show()

    #     print("\nTry to maintain a balanced gaze, Enhance focus on the middle upto 80% and try to reduce focus on other sides.\nThis can create a strong sense of engagement and connection in  your interection")
        
    gaze_track_dictionary = dict()
    gaze_track_dictionary['left_look_percentage']       = round(left_percentage,2)
    gaze_track_dictionary['right_percentage']           = round(right_percentage,2)
    gaze_track_dictionary['up_percentage']              = round(up_percentage,2)
    gaze_track_dictionary['down_percentage']            = round(down_percentage,2)
    gaze_track_dictionary['middle_percentage']          = round(middle_percentage,2)
    gaze_track_dictionary['overall_gaze_percentage']    = round(overall_gaze_percentage,2)
    
    
    # gaze_track_dictionary['blinking_percentage']  = round(blinking_percentage,2)
    
    return gaze_track_dictionary
