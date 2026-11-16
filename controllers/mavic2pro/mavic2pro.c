/*
 * AERIS - AI Drone System for Autonomous Emergency Response
 * Mavic 2 PRO Controller
 *
 * - Original Mavic stabilisation preserved.
 * - Keyboard controls preserved.
 * - Flask emergency mission reading.
 * - GPS and compass diagnostics.
 * - Camera motors kept neutral.
 * - Target flight altitude: 5 metres.
 *
 * Autonomous navigation is the next development stage.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>

#include <webots/robot.h>
#include <webots/camera.h>
#include <webots/compass.h>
#include <webots/gps.h>
#include <webots/gyro.h>
#include <webots/inertial_unit.h>
#include <webots/keyboard.h>
#include <webots/led.h>
#include <webots/motor.h>

#define CLAMP(value, low, high) \
  ((value) < (low) ? (low) : ((value) > (high) ? (high) : (value)))

#define MISSION_FILE \
  "C:/Users/Nobubele Sibanda/OneDrive - Richfield Graduate Institute of Technology/Desktop/AERIS_Project/mission_bridge/mission.txt"


typedef struct {
  int incident_id;
  char incident_type[50];
  char location[100];
  char severity[20];
  double mission_x;
  double mission_y;
  char status[30];
} AerisMission;


// ==================================================
// READ JSON STRING
// ==================================================

static bool read_json_string(
  const char *json,
  const char *key,
  char *output,
  size_t output_size
) {
  char search_key[100];

  snprintf(search_key, sizeof(search_key), "\"%s\"", key);

  const char *position = strstr(json, search_key);

  if (position == NULL)
    return false;

  position = strchr(position, ':');

  if (position == NULL)
    return false;

  position++;

  while (*position == ' ' || *position == '\t' ||
         *position == '\n' || *position == '\r') {
    position++;
  }

  if (*position != '"')
    return false;

  position++;

  const char *end = strchr(position, '"');

  if (end == NULL)
    return false;

  size_t length = (size_t)(end - position);

  if (length >= output_size)
    length = output_size - 1;

  memcpy(output, position, length);
  output[length] = '\0';

  return true;
}


// ==================================================
// READ JSON NUMBER
// ==================================================

static bool read_json_number(
  const char *json,
  const char *key,
  double *output
) {
  char search_key[100];

  snprintf(search_key, sizeof(search_key), "\"%s\"", key);

  const char *position = strstr(json, search_key);

  if (position == NULL)
    return false;

  position = strchr(position, ':');

  if (position == NULL)
    return false;

  position++;

  while (*position == ' ' || *position == '\t' ||
         *position == '\n' || *position == '\r') {
    position++;
  }

  char *end_pointer;
  double value = strtod(position, &end_pointer);

  if (position == end_pointer)
    return false;

  *output = value;

  return true;
}


// ==================================================
// READ AERIS MISSION
// ==================================================

static bool read_aeris_mission(AerisMission *mission) {

  FILE *file = fopen(MISSION_FILE, "r");

  if (file == NULL) {
    printf("[AERIS] Mission file not found: %s\n", MISSION_FILE);
    return false;
  }

  char json[2048];

  size_t bytes_read = fread(json, 1, sizeof(json) - 1, file);

  json[bytes_read] = '\0';

  fclose(file);

  if (bytes_read == 0) {
    printf("[AERIS] Mission file is empty.\n");
    return false;
  }

  double incident_id;

  if (!read_json_number(json, "incident_id", &incident_id) ||
      !read_json_number(json, "x_coordinate", &mission->mission_x) ||
      !read_json_number(json, "z_coordinate", &mission->mission_y) ||
      !read_json_string(json, "incident_type",
                        mission->incident_type,
                        sizeof(mission->incident_type)) ||
      !read_json_string(json, "location",
                        mission->location,
                        sizeof(mission->location)) ||
      !read_json_string(json, "severity",
                        mission->severity,
                        sizeof(mission->severity)) ||
      !read_json_string(json, "status",
                        mission->status,
                        sizeof(mission->status))) {

    printf("[AERIS] Could not read all mission details.\n");
    return false;
  }

  mission->incident_id = (int)incident_id;

  if (strcmp(mission->status, "Pending") != 0) {
    printf("[AERIS] Mission is not pending. Status: %s\n",
           mission->status);
    return false;
  }

  return true;
}


// ==================================================
// MAIN PROGRAM
// ==================================================

int main(int argc, char **argv) {

  wb_robot_init();

  int timestep = (int)wb_robot_get_basic_time_step();


  // INITIALISE DEVICES

  WbDeviceTag camera = wb_robot_get_device("camera");
  wb_camera_enable(camera, timestep);

  WbDeviceTag front_left_led =
    wb_robot_get_device("front left led");

  WbDeviceTag front_right_led =
    wb_robot_get_device("front right led");

  WbDeviceTag imu = wb_robot_get_device("inertial unit");
  wb_inertial_unit_enable(imu, timestep);

  WbDeviceTag gps = wb_robot_get_device("gps");
  wb_gps_enable(gps, timestep);

  WbDeviceTag compass = wb_robot_get_device("compass");
  wb_compass_enable(compass, timestep);

  WbDeviceTag gyro = wb_robot_get_device("gyro");
  wb_gyro_enable(gyro, timestep);

  wb_keyboard_enable(timestep);


  // CAMERA MOTORS

  WbDeviceTag camera_roll_motor =
    wb_robot_get_device("camera roll");

  WbDeviceTag camera_pitch_motor =
    wb_robot_get_device("camera pitch");


  // PROPELLER MOTORS

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

  for (int m = 0; m < 4; ++m) {
    wb_motor_set_position(motors[m], INFINITY);
    wb_motor_set_velocity(motors[m], 1.0);
  }


  // AERIS STARTUP

  printf("\n====================================\n");
  printf("       AERIS DRONE SYSTEM\n");
  printf("       Mavic 2 PRO Controller\n");
  printf("====================================\n");


  while (wb_robot_step(timestep) != -1) {
    if (wb_robot_get_time() > 1.0)
      break;
  }


  // READ AERIS MISSION

  AerisMission mission = {0};

  bool mission_loaded = read_aeris_mission(&mission);

  if (mission_loaded) {

    printf("\n[AERIS] MISSION RECEIVED SUCCESSFULLY\n");
    printf("------------------------------------\n");

    printf("Incident ID : %d\n", mission.incident_id);
    printf("Incident    : %s\n", mission.incident_type);
    printf("Location    : %s\n", mission.location);
    printf("Severity    : %s\n", mission.severity);
    printf("Destination X: %.2f\n", mission.mission_x);
    printf("Destination Y: %.2f\n", mission.mission_y);
    printf("Status      : %s\n", mission.status);

    printf("------------------------------------\n");

  } else {
    printf("\n[AERIS] No valid pending mission loaded.\n");
  }

  printf("\nOriginal Mavic keyboard controls remain enabled.\n");
  printf("[AERIS] GPS and compass diagnostics enabled.\n");


  // MAVIC STABILISATION SETTINGS

  const double k_vertical_thrust = 68.5;
  const double k_vertical_offset = 0.6;
  const double k_vertical_p = 3.0;

  const double k_roll_p = 50.0;
  const double k_pitch_p = 30.0;

  // UPDATED TARGET ALTITUDE
  double target_altitude = 5.0;

  double next_gps_print = 0.0;


  // MAIN CONTROL LOOP

  while (wb_robot_step(timestep) != -1) {

    const double time = wb_robot_get_time();

    const double *imu_values =
      wb_inertial_unit_get_roll_pitch_yaw(imu);

    const double roll = imu_values[0];
    const double pitch = imu_values[1];

    const double *gps_values =
      wb_gps_get_values(gps);

    const double altitude = gps_values[2];

    const double *north =
      wb_compass_get_values(compass);

    const double heading =
      atan2(north[0], north[2]);


    // GYROSCOPE

    const double roll_velocity =
      wb_gyro_get_values(gyro)[0];

    const double pitch_velocity =
      wb_gyro_get_values(gyro)[1];


    // GPS AND COMPASS DIAGNOSTICS

    if (time >= next_gps_print) {

      printf(
        "[AERIS GPS] X: %.2f | Y: %.2f | Z: %.2f | Heading: %.2f\n",
        gps_values[0],
        gps_values[1],
        gps_values[2],
        heading
      );

      next_gps_print = time + 2.0;
    }


    // LED INDICATORS

    const bool led_state = ((int)time) % 2;

    wb_led_set(front_left_led, led_state);
    wb_led_set(front_right_led, !led_state);


    // CAMERA STABILISATION

    wb_motor_set_position(camera_roll_motor, 0.0);
    wb_motor_set_position(camera_pitch_motor, 0.0);


    // KEYBOARD CONTROLS

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
          printf("Target altitude: %.2f m\n", target_altitude);
          break;

        case (WB_KEYBOARD_SHIFT + WB_KEYBOARD_DOWN):
          target_altitude -= 0.05;
          printf("Target altitude: %.2f m\n", target_altitude);
          break;
      }

      key = wb_keyboard_get_key();
    }


    // STABILISATION

    const double roll_input =
      k_roll_p * CLAMP(roll, -1.0, 1.0) +
      roll_velocity + roll_disturbance;

    const double pitch_input =
      k_pitch_p * CLAMP(pitch, -1.0, 1.0) +
      pitch_velocity + pitch_disturbance;

    const double yaw_input = yaw_disturbance;


    // ALTITUDE CONTROL

    const double clamped_difference_altitude =
      CLAMP(
        target_altitude - altitude + k_vertical_offset,
        -1.0,
        1.0
      );

    const double vertical_input =
      k_vertical_p * pow(clamped_difference_altitude, 3.0);


    // MOTOR CONTROL

    const double front_left_motor_input =
      k_vertical_thrust + vertical_input -
      roll_input + pitch_input - yaw_input;

    const double front_right_motor_input =
      k_vertical_thrust + vertical_input +
      roll_input + pitch_input + yaw_input;

    const double rear_left_motor_input =
      k_vertical_thrust + vertical_input -
      roll_input - pitch_input + yaw_input;

    const double rear_right_motor_input =
      k_vertical_thrust + vertical_input +
      roll_input - pitch_input - yaw_input;


    wb_motor_set_velocity(front_left_motor, front_left_motor_input);
    wb_motor_set_velocity(front_right_motor, -front_right_motor_input);
    wb_motor_set_velocity(rear_left_motor, -rear_left_motor_input);
    wb_motor_set_velocity(rear_right_motor, rear_right_motor_input);

  }


  wb_robot_cleanup();

  return EXIT_SUCCESS;
}