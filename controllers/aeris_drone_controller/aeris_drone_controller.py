from controller import Robot

robot = Robot()
timestep = int(robot.getBasicTimeStep())

camera = robot.getDevice("camera")
camera.enable(timestep)

print("AERIS drone controller started.")
print("Drone camera activated successfully.")

while robot.step(timestep) != -1:
    image = camera.getImage()

    if image is not None:
        print("AERIS camera is capturing images.")