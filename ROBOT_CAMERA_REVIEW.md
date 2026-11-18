# Camera compatibility review — 2026-11-18

## Scope and conclusion

Review performed on Windows, without robot access. The supplied label reads
ASC60C, W:640*480. The user reports 15 FPS. Treat 640x480 at 15 FPS as the
deployment input; do not require HD or change the camera driver for face verification.

Hiwonder's Nuwa-HP60C page documents RGB888 and a recommended 640x480 mode:
https://www.hiwonder.com/products/ros-real-sense-depth-camera
This is related vendor documentation, not proof that the ASC60C-labelled unit has
every HP60C specification. Confirm the actual device model and ROS output on the robot.

The face image pipeline supports VGA. This does not establish recognition accuracy
under the robot's lighting, mounting angle, focus or network conditions.

## Code review

- Default input: `/ascamera/camera_publisher/rgb0/image`, a ROS color Image topic.
  Use RGB/BGR input, not the RAW16 depth topic. No second USB camera driver is opened.
- ROS subscription uses BEST_EFFORT, depth 1. The face scanner samples at 2 Hz;
  it sends at most one request at a time with at least one second between submissions.
- JPEG encoding preserves a 640x480 input; configured 960x720 bounds are maximums,
  not an instruction to upscale. RGB conversion and padded row strides are supported.
- Samples older than 0.5 seconds locally are discarded; source timestamps are checked
  against the ROS clock (default maximum source age 0.35 seconds).
- AI requires exactly one face, face crop dimensions at least 80x80 pixels,
  and Laplacian sharpness >=40 after quality normalization. Do not lower quality or
  similarity thresholds merely to compensate for a distant face at VGA resolution.
- Backend AI request timeout is 5 seconds. Pi's HTTP socket timeout is 6 seconds,
  allowing backend response overhead; it is not a guaranteed total wall-clock deadline
  because authentication refresh can retry. Workflow authorization still expires.
- AI results do not directly move the servo. Backend checks robot, step, transport,
  staff, avatar version, cancellation and session validity before issuing authorization.
- Fixed a scanner exit on camera-open/JPEG exceptions; it now retries without
  submitting the invalid frame. Removed duplicated configuration validation.

## Verification

- AI: 16 tests passed with actual YuNet/SFace model files and public portrait fixtures.
  Added VGA JPEG quality 85 match/wrong-person tests, preserving aspect ratio.
  Same-person fixture is an image transformation, not an independent camera capture;
  these tests are regression checks, not a biometric accuracy benchmark.
- Focused Pi: face scanner 7, VGA camera 2, camera stream 14 tests passed.
  Simulated 15 FPS source, 2 Hz sampling, latest-frame behavior, expired frames,
  RGB row padding, JPEG dimensions, camera recovery and encoder recovery.
- Backend: 162 tests, 0 failures, 0 errors, 1 skipped.
- Frontend: production build passed; existing bundler directive warnings remain.
- No camera captures, staff images or biometric templates were added to this report.

## Required robot checks before enabling delivery

In the robot's existing ROS environment, inspect the configured topic:

```bash
ros2 topic list -t
ros2 topic info /ascamera/camera_publisher/rgb0/image --verbose
ros2 topic hz /ascamera/camera_publisher/rgb0/image
```

Confirm Image width=640, height=480, encoding rgb8/bgr8 (or another supported color
encoding), fresh header stamps and approximately the reported 15 FPS. Confirm camera
and worker use compatible ROS clocks and that the actual frame shows a clear face.

Keep face verification disabled until:

1. Backend migration, service credentials, HTTPS Pi access and AI readiness are verified.
2. Avatars are enrolled and approved using the current pipeline/modelVersion.
   Existing templates from before the image-quality pipeline change must be recreated.
3. Actual camera captures pass testing for both staff, wrong people, no face,
   multiple faces, blur, network loss and avatar replacement during verification.
4. A supervised QR delivery and face delivery complete pickup, locking, delivery and
   final locking. Verify denied cases never produce an unlock authorization.

The demo has no photo/video liveness protection. A depth camera alone does not add
anti-spoofing to this RGB-only implementation. No robot deployment was performed.

## Full Pi suite findings (not a deployment pass)

Isolated each of 51 test modules on Windows, with a 30-second timeout per module: 34 passed, 16 failed, 1 timed out. The initial combined discovery was stopped after stalled progress; isolated results below replace that incomplete run.

Failures include Windows-only process API absence (`os.WNOHANG`), incomplete test doubles (`cfg`, `node`, `scans`, `imu_problem`), and actual expectation mismatches in motion, obstacle limiting and navigation. They cannot all be attributed to Windows. These subsystems were not modified by this camera review; their failures must be triaged before autonomous robot deployment.

- FAIL: `test_autonomous_mapping.py`
- FAIL: `test_autonomy_speed.py`
- FAIL: `test_geometry_diagnostics.py`
- FAIL: `test_manual_drive.py`
- FAIL: `test_mapping_navigator.py`
- FAIL: `test_mecanum_runtime.py`
- FAIL: `test_motion_speed.py`
- FAIL: `test_move_forward_profile.py`
- FAIL: `test_move_position_only.py`
- FAIL: `test_navigation_authorization.py`
- FAIL: `test_navigation_session.py`
- TIMEOUT: `test_navigation_smooth.py`
- FAIL: `test_navigation_zones.py`
- FAIL: `test_optional_us100.py`
- FAIL: `test_slam_session.py`
- FAIL: `test_stack_startup.py`
- FAIL: `test_vendor_yaw_plan.py`

Detailed local test output: `%TEMP%/face-pi-isolated-audit.json`. A timeout is an incomplete test, not proof of a runtime defect.
