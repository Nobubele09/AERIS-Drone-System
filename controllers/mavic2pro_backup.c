/*
 * Copyright 1996-2024 Cyberbotics Ltd.
 *
 * Licensed under the Apache License, Version 2.0.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>

#include <webots/robot.h>
#include <webots/camera.h>
#include <webots/compass.h>
#include <webots/gps.h>
#include <webots/gyro.h>
#include <webots/inertial_unit.h>
#include <webots/keyboard.h>
#include <webots/led.h>
#include <webots/motor.h>

#define SIGN(x) ((x) > 0) - ((x) < 0)
#define CLAMP(value, low, high) \
  ((value) < (low) ? (low) : ((value) > (high) ? (high) : (value)))

int main(int argc, char **argv) {

  // ==================================================
  // INITIALISE WEBOTS
  // ==================================================

  wb_robot_init();

  int timestep = (int)wb_robot_get_basic_time_step();

  // ==================================================
  // GET AND ENABLE DEVICES
  // ==================================================

  WbDeviceTag camera = wb_robot_get_device("camera");
  wb_camera_enable(camera, timestep);

  WbDeviceTag front_left_led =
      wb_robot_get_device("front left led");

  WbDeviceTag front_right_led =
      wb_robot_get_device("front right led");

  WbDeviceTag imu =
      wb_robot_get_device("inertial unit");

  wb_inertial_unit_enable(imu, timestep);

  WbDeviceTag gps =
      wb_robot_get_device("gps");

  wb_gps_enable(gps, timestep);

  WbDeviceTag compass =
      wb_robot_get_device("compass");

  wb_compass_enable(compass, timestep);

  WbDeviceTag gyro =
      wb_robot_get_device("gyro");

  wb_gyro_enable(gyro, timestep);

  wb_keyboard_enable(timestep);

  WbDeviceTag camera_roll_motor =
      wb_robot_get_device("camera roll");

  WbDeviceTag camera_pitch_motor =
      wb_robot_get_device("camera pitch");

  // ==================================================
  // GET DRONE PROPELLER MOTORS
  // ==================================================

  WbDeviceTag front_left_motor =
      wb_robot_get_device("front left propeller");

  WbDeviceTag front_right_motor =
      wb_robot_get_device("front right propeller");

  WbDeviceTag rear_left_motor =
      wb_robot_get_device("rear left propeller");

  WbDeviceTag rear_right_motor =
      wb_robot_get_device("rear right propeller");

  WbDeviceTag motors[4] = {
      front_left_motor,
      front_right_motor,
      rear_left_motor,
      rear_right_motor
  };

  int m;

  for (m = 0; m < 4; ++m) {

    wb_motor_set_position(motors[m], INFINITY);

    wb_motor_set_velocity(motors[m], 1.0);
  }

  // ==================================================
  // START DRONE
  // ==================================================

  printf("\n");
  printf("========================================\n");
  printf("       AERIS DRONE SYSTEM STARTED       \n");
  printf("========================================\n");

  printf("Initialising Mavic 2 PRO...\n");

  // Wait one second before starting flight.
  while (wb_robot_step(timestep) != -1) {

    if (wb_robot_get_time() > 1.0)
      break;
  }

  printf("\n");
  printf("AERIS drone is ready.\n");

  // ==================================================
  // KEYBOARD CONTROL INFORMATION
  // ==================================================

  printf("\n");
  printf("MANUAL DRONE CONTROLS:\n");

  printf("----------------------------------------\n");

  printf("UP                 : Move forward\n");
  printf("DOWN               : Move backward\n");
  printf("RIGHT              : Turn right\n");
  printf("LEFT               : Turn left\n");

  printf("SHIFT + UP         : Increase altitude\n");
  printf("SHIFT + DOWN       : Decrease altitude\n");

  printf("SHIFT + RIGHT      : Strafe right\n");
  printf("SHIFT + LEFT       : Strafe left\n");

  printf("----------------------------------------\n");

  // ==================================================
  // DRONE STABILISATION CONSTANTS
  // ==================================================

  const double k_vertical_thrust = 68.5;

  const double k_vertical_offset = 0.6;

  const double k_vertical_p = 3.0;

  const double k_roll_p = 50.0;

  const double k_pitch_p = 30.0;

  // ==================================================
  // DRONE VARIABLES
  // ==================================================

  double target_altitude = 1.0;

  // Time of the last camera image save.
  double last_image_save_time = 0.0;

  // ==================================================
  // MAIN DRONE CONTROL LOOP
  // ==================================================

  while (wb_robot_step(timestep) != -1) {

    const double time = wb_robot_get_time();

    // ==================================================
    // AUTOMATIC CAMERA IMAGE CAPTURE
    // ==================================================

    if (time - last_image_save_time >= 5.0) {

      int result = wb_camera_save_image(
          camera,
          "aeris_camera.jpg",
          90
      );

      if (result == 0) {

        printf(
            "AERIS: Camera image saved successfully.\n"
        );

      } else {

        printf(
            "AERIS: Camera image could not be saved.\n"
        );
      }

      last_image_save_time = time;
    }

    // ==================================================
    // READ DRONE SENSOR VALUES
    // ==================================================

    const double roll =
        wb_inertial_unit_get_roll_pitch_yaw(imu)[0];

    const double pitch =
        wb_inertial_unit_get_roll_pitch_yaw(imu)[1];

    const double altitude =
        wb_gps_get_values(gps)[2];

    const double roll_velocity =
        wb_gyro_get_values(gyro)[0];

    const double pitch_velocity =
        wb_gyro_get_values(gyro)[1];

    // ==================================================
    // CONTROL FRONT LED LIGHTS
    // ==================================================

    const bool led_state = ((int)time) % 2;

    wb_led_set(front_left_led, led_state);

    wb_led_set(front_right_led, !led_state);

    // ==================================================
    // STABILISE CAMERA
    // ==================================================

    wb_motor_set_position(
        camera_roll_motor,
        -0.115 * roll_velocity
    );

    wb_motor_set_position(
        camera_pitch_motor,
        -0.1 * pitch_velocity
    );

    // ==================================================
    // KEYBOARD INPUT
    // ==================================================

    double roll_disturbance = 0.0;

    double pitch_disturbance = 0.0;

    double yaw_disturbance = 0.0;

    int key = wb_keyboard_get_key();

    while (key > 0) {

      switch (key) {

        case WB_KEYBOARD_UP:

          pitch_disturbance = -2.0;

          break;

        case WB_KEYBOARD_DOWN:

          pitch_disturbance = 2.0;

          break;

        case WB_KEYBOARD_RIGHT:

          yaw_disturbance = -1.3;

          break;

        case WB_KEYBOARD_LEFT:

          yaw_disturbance = 1.3;

          break;

        case (WB_KEYBOARD_SHIFT + WB_KEYBOARD_RIGHT):

          roll_disturbance = -1.0;

          break;

        case (WB_KEYBOARD_SHIFT + WB_KEYBOARD_LEFT):

          roll_disturbance = 1.0;

          break;

        case (WB_KEYBOARD_SHIFT + WB_KEYBOARD_UP):

          target_altitude += 0.05;

          printf(
              "Target altitude: %f [m]\n",
              target_altitude
          );

          break;

        case (WB_KEYBOARD_SHIFT + WB_KEYBOARD_DOWN):

          target_altitude -= 0.05;

          printf(
              "Target altitude: %f [m]\n",
              target_altitude
          );

          break;
      }

      key = wb_keyboard_get_key();
    }

    // ==================================================
    // CALCULATE DRONE STABILISATION INPUTS
    // ==================================================

    const double roll_input =
        k_roll_p * CLAMP(roll, -1.0, 1.0)
        + roll_velocity
        + roll_disturbance;

    const double pitch_input =
        k_pitch_p * CLAMP(pitch, -1.0, 1.0)
        + pitch_velocity
        + pitch_disturbance;

    const double yaw_input =
        yaw_disturbance;

    const double clamped_difference_altitude =
        CLAMP(
            target_altitude - altitude + k_vertical_offset,
            -1.0,
            1.0
        );

    const double vertical_input =
        k_vertical_p * pow(
            clamped_difference_altitude,
            3.0
        );

    // ==================================================
    // CALCULATE MOTOR SPEEDS
    // ==================================================

    const double front_left_motor_input =
        k_vertical_thrust
        + vertical_input
        - roll_input
        + pitch_input
        - yaw_input;

    const double front_right_motor_input =
        k_vertical_thrust
        + vertical_input
        + roll_input
        + pitch_input
        + yaw_input;

    const double rear_left_motor_input =
        k_vertical_thrust
        + vertical_input
        - roll_input
        - pitch_input
        + yaw_input;

    const double rear_right_motor_input =
        k_vertical_thrust
        + vertical_input
        + roll_input
        - pitch_input
        - yaw_input;

    // ==================================================
    // APPLY MOTOR SPEEDS
    // ==================================================

    wb_motor_set_velocity(
        front_left_motor,
        front_left_motor_input
    );

    wb_motor_set_velocity(
        front_right_motor,
        -front_right_motor_input
    );

    wb_motor_set_velocity(
        rear_left_motor,
        -rear_left_motor_input
    );

    wb_motor_set_velocity(
        rear_right_motor,
        rear_right_motor_input
    );
  }

  // ==================================================
  // CLEAN UP WEBOTS
  // ==================================================

  wb_robot_cleanup();

  return EXIT_SUCCESS;
}