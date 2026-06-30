"""Curated MyPilot settings catalog.

Derived from SunnyPilot's live ``settings_ui.schema`` (panels/sections, exact option
labels/values, ranges, defaults) cross-referenced with the public source for safety
annotations (offroad gating, reboot, danger level) and remote-configurability. This is the
seed for ``setting_definitions``. Internal/system params (CarParams, Git*, Offroad_* alerts,
Live*, ApiCache_*) are intentionally excluded — they are not user-facing.

``capability`` gates visibility: the setting is shown only when the device reports that
capability truthy (e.g. ``torque_allowed``, ``enable_bsm``). ``None`` = always shown.
"""

from __future__ import annotations

from .models import DangerLevel, SettingType

CAUTION = DangerLevel.CAUTION
DANGEROUS = DangerLevel.DANGEROUS

# Panel display order + labels + icons (mirrors SunnyLink's panel set).
PANELS: list[dict] = [
    {"id": "toggles", "label": "Toggles", "order": 1},
    {"id": "steering", "label": "Steering", "order": 2},
    {"id": "cruise", "label": "Cruise", "order": 3},
    {"id": "visuals", "label": "Visuals", "order": 4},
    {"id": "display", "label": "Display", "order": 5},
    {"id": "models", "label": "Models", "order": 6},
    {"id": "device", "label": "Device", "order": 7},
    {"id": "software", "label": "Software", "order": 8},
    {"id": "developer", "label": "Developer", "order": 9},
]


def _opt(*pairs) -> list[dict]:
    return [{"value": value, "label": label} for value, label in pairs]


# Each entry is normalized by seed.py; omitted fields take sensible defaults
# (type-from-default, danger=safe, requires_offroad/reboot=False, remote_configurable=True).
SETTINGS: list[dict] = [
    # ---- Toggles -------------------------------------------------------------------------
    {"key": "OpenpilotEnabledToggle", "label": "Enable sunnypilot", "panel": "toggles",
     "section": "Core", "default": True, "requires_offroad": True, "requires_reboot": True,
     "danger": CAUTION,
     "description": "Use the sunnypilot system for adaptive cruise and lane-keep assist. Your attention is required at all times."},
    {"key": "IsLdwEnabled", "label": "Lane Departure Warnings", "panel": "toggles",
     "section": "Core", "default": False,
     "description": "Alerts to steer back into the lane when the vehicle drifts above ~31 mph."},
    {"key": "AlwaysOnDM", "label": "Always-On Driver Monitoring", "panel": "toggles",
     "section": "Core", "default": False,
     "description": "Enable driver monitoring even when sunnypilot is not engaged."},
    {"key": "IsMetric", "label": "Use Metric System", "panel": "toggles", "section": "Core",
     "default": False, "description": "Display speed in km/h instead of mph."},
    {"key": "RecordFront", "label": "Record & Upload Driver Camera", "panel": "toggles",
     "section": "Recording", "default": False, "requires_reboot": True, "danger": CAUTION,
     "description": "Upload driver-facing camera data to help improve driver monitoring."},
    {"key": "RecordAudio", "label": "Record & Upload Microphone Audio", "panel": "toggles",
     "section": "Recording", "default": False, "requires_reboot": True, "danger": CAUTION,
     "description": "Record and store microphone audio while driving."},

    # ---- Steering ------------------------------------------------------------------------
    {"key": "Mads", "label": "Modular Assistive Driving System (MADS)", "panel": "steering",
     "section": "MADS", "default": True, "requires_offroad": True, "danger": CAUTION,
     "description": "Enable MADS. Disable to revert to stock sunnypilot engagement behavior."},
    {"key": "BlinkerPauseLateralControl", "label": "Pause Lateral Control with Blinker",
     "panel": "steering", "section": "Blinker Control", "default": False, "danger": CAUTION,
     "description": "Pause lateral control with the blinker when below the selected speed."},
    {"key": "BlinkerMinLateralControlSpeed", "label": "Min Speed to Pause Lateral Control",
     "panel": "steering", "section": "Blinker Control", "type": SettingType.NUMBER,
     "default": 20, "min": 0, "max": 255, "step": 5,
     "description": "Speed below which lateral control pauses with the blinker."},
    {"key": "EnforceTorqueControl", "label": "Enforce Torque Lateral Control",
     "panel": "steering", "section": "Torque Control", "default": False,
     "requires_offroad": True, "danger": CAUTION, "capability": "torque_allowed",
     "description": "Force sunnypilot to steer using Torque lateral control."},
    {"key": "AutoLaneChangeTimer", "label": "Auto Lane Change by Blinker", "panel": "steering",
     "section": "Lane Change", "type": SettingType.ENUM, "default": 0, "danger": CAUTION,
     "options": _opt((-1, "Off"), (0, "Nudge"), (1, "Nudgeless"), (2, "0.5s"), (3, "1s"),
                     (4, "2s"), (5, "3s")),
     "description": "Delay before an auto lane change. Use caution with this feature."},
    {"key": "AutoLaneChangeBsmDelay", "label": "Auto Lane Change: Delay with Blind Spot",
     "panel": "steering", "section": "Lane Change", "default": False, "capability": "enable_bsm",
     "description": "Delay lane change when blind-spot monitoring detects a vehicle."},

    # ---- Cruise --------------------------------------------------------------------------
    {"key": "ExperimentalMode", "label": "Experimental Mode", "panel": "cruise",
     "section": "Core", "default": False, "danger": DANGEROUS,
     "capability": "has_longitudinal_control",
     "description": "End-to-end longitudinal control. Alpha quality — mistakes should be expected."},
    {"key": "DynamicExperimentalControl", "label": "Dynamic Experimental Control",
     "panel": "cruise", "section": "Core", "default": False, "danger": CAUTION,
     "capability": "has_longitudinal_control",
     "description": "Let the model decide when to use ACC vs end-to-end longitudinal."},
    {"key": "DisengageOnAccelerator", "label": "Disengage on Accelerator Pedal",
     "panel": "cruise", "section": "Core", "default": False, "danger": CAUTION,
     "description": "Pressing the accelerator pedal disengages sunnypilot."},
    {"key": "LongitudinalPersonality", "label": "Driving Personality", "panel": "cruise",
     "section": "Core", "type": SettingType.ENUM, "default": 1, "danger": CAUTION,
     "options": _opt((0, "Aggressive"), (1, "Standard"), (2, "Relaxed")),
     "description": "Following distance / aggressiveness. Standard is recommended."},
    {"key": "IntelligentCruiseButtonManagement",
     "label": "Intelligent Cruise Button Management (ICBM)", "panel": "cruise",
     "section": "Core", "default": False, "requires_offroad": True, "danger": DANGEROUS,
     "capability": "icbm_available",
     "description": "Emulate cruise button presses for limited longitudinal control (alpha)."},
    {"key": "SmartCruiseControlVision", "label": "Smart Cruise Control – Vision",
     "panel": "cruise", "section": "Smart Cruise Control", "default": False, "danger": CAUTION,
     "description": "Use vision predictions to slow for upcoming curves."},
    {"key": "SmartCruiseControlMap", "label": "Smart Cruise Control – Map", "panel": "cruise",
     "section": "Smart Cruise Control", "default": False, "danger": CAUTION,
     "description": "Use map data to slow for upcoming curves."},
    {"key": "SpeedLimitMode", "label": "Speed Limit Assist Mode", "panel": "cruise",
     "section": "Speed Limits", "type": SettingType.ENUM, "default": 1, "danger": CAUTION,
     "options": _opt((0, "Off"), (1, "Information"), (2, "Warning"), (3, "Assist")),
     "description": "Off / show info / warn / actively adjust cruise speed to the limit."},
    {"key": "SpeedLimitPolicy", "label": "Speed Limit Source", "panel": "cruise",
     "section": "Speed Limits", "type": SettingType.ENUM, "default": 3,
     "options": _opt((0, "Car State Only"), (1, "Map Data Only"), (2, "Car State Priority"),
                     (3, "Map Data Priority"), (4, "Combined")),
     "description": "Which source to prefer for speed-limit data."},

    # ---- Visuals -------------------------------------------------------------------------
    {"key": "BlindSpot", "label": "Show Blind Spot Warnings", "panel": "visuals",
     "section": "HUD Elements", "default": False, "capability": "enable_bsm",
     "description": "Display a warning when a vehicle is detected in your blind spot."},
    {"key": "TorqueBar", "label": "Steering Arc", "panel": "visuals", "section": "HUD Elements",
     "default": False, "description": "Show a steering arc on the driving screen."},
    {"key": "ShowTurnSignals", "label": "Display Turn Signals", "panel": "visuals",
     "section": "HUD Elements", "default": False,
     "description": "Draw turn indicators on the HUD."},
    {"key": "RoadNameToggle", "label": "Display Road Name", "panel": "visuals",
     "section": "HUD Elements", "default": False,
     "description": "Show the current road name (requires downloaded OSM data)."},
    {"key": "StandstillTimer", "label": "Standstill Timer", "panel": "visuals",
     "section": "HUD Elements", "default": False,
     "description": "Show a timer on the HUD when the car is stopped."},
    {"key": "ChevronInfo", "label": "Metrics Below Chevron", "panel": "visuals",
     "section": "HUD Elements", "type": SettingType.ENUM, "default": 4,
     "capability": "has_longitudinal_control",
     "options": _opt((0, "Off"), (1, "Distance"), (2, "Speed"), (3, "Time"), (4, "All")),
     "description": "Useful metrics displayed below the lead chevron."},
    {"key": "DevUIInfo", "label": "Developer UI", "panel": "visuals",
     "section": "Developer UI Info", "type": SettingType.ENUM, "default": 0,
     "options": _opt((0, "Off"), (1, "Bottom"), (2, "Right"), (3, "Right & Bottom")),
     "description": "Display real-time parameters and metrics."},
    {"key": "GreenLightAlert", "label": "Green Traffic Light Alert (Beta)", "panel": "visuals",
     "section": "Alerts & Extras", "default": False, "danger": CAUTION,
     "description": "Chime + alert when a traffic light turns green."},
    {"key": "LeadDepartAlert", "label": "Lead Departure Alert (Beta)", "panel": "visuals",
     "section": "Alerts & Extras", "default": False, "danger": CAUTION,
     "description": "Chime + alert when the vehicle in front starts moving."},
    {"key": "RainbowMode", "label": "Tesla Rainbow Mode", "panel": "visuals",
     "section": "Alerts & Extras", "default": False,
     "description": "A rainbow effect on the path. Does not affect driving."},

    # ---- Display -------------------------------------------------------------------------
    {"key": "OnroadScreenOffBrightness", "label": "Onroad Brightness", "panel": "display",
     "section": "Brightness & Timeout", "type": SettingType.ENUM, "default": 0,
     "options": _opt((0, "Auto"), (1, "Auto (Dark)"), (2, "Screen Off"), (5, "15%"),
                     (10, "40%"), (15, "65%"), (22, "100%")),
     "description": "Screen brightness while onroad."},
    {"key": "OnroadScreenOffTimer", "label": "Onroad Brightness Delay", "panel": "display",
     "section": "Brightness & Timeout", "type": SettingType.ENUM, "default": 15,
     "options": _opt((3, "3s"), (5, "5s"), (15, "15s"), (30, "30s"), (60, "1m"), (300, "5m"),
                     (600, "10m")),
     "description": "Delay before the onroad brightness setting applies."},
    {"key": "InteractivityTimeout", "label": "Interactivity Timeout", "panel": "display",
     "section": "Brightness & Timeout", "type": SettingType.ENUM, "default": 0,
     "options": _opt((0, "Default"), (10, "10s"), (30, "30s"), (60, "1m"), (120, "2m")),
     "description": "Time before the settings UI closes automatically when idle."},

    # ---- Models --------------------------------------------------------------------------
    {"key": "LaneTurnDesire", "label": "Use Lane Turn Desires", "panel": "models",
     "section": "Model Behavior", "default": False, "danger": CAUTION,
     "description": "Plan turns at low speed with the blinker on to prevent wrong-direction turns."},
    {"key": "LaneTurnValue", "label": "Lane Turn Speed", "panel": "models",
     "section": "Model Behavior", "type": SettingType.NUMBER, "default": 19.0, "min": 0,
     "max": 20, "step": 1, "description": "Maximum speed for lane turn desires."},
    {"key": "LagdToggle", "label": "Live Learning Steer Delay", "panel": "models",
     "section": "Model Behavior", "default": True, "danger": CAUTION,
     "description": "Let the car learn and adapt its steering response time."},
    {"key": "LagdToggleDelay", "label": "Manual Software Delay", "panel": "models",
     "section": "Model Behavior", "type": SettingType.NUMBER, "default": 0.2, "min": 0.05,
     "max": 0.5, "step": 0.01, "description": "Software delay used when Live Learning is off."},
    {"key": "NeuralNetworkLateralControl", "label": "Neural Network Lateral Control (NNLC)",
     "panel": "models", "section": "Lateral Control", "default": False,
     "requires_offroad": True, "danger": CAUTION, "capability": "torque_allowed",
     "description": "Use a neural-network lateral controller (torque vehicles)."},
    {"key": "CameraOffset", "label": "Adjust Camera Offset", "panel": "models",
     "section": "Camera", "type": SettingType.NUMBER, "default": 0.0, "min": -0.35, "max": 0.35,
     "step": 0.01, "danger": CAUTION,
     "description": "Lateral camera offset for lane positioning."},

    # ---- Device --------------------------------------------------------------------------
    {"key": "OffroadMode", "label": "Force Always-Offroad", "panel": "device",
     "section": "General", "default": False, "danger": CAUTION,
     "description": "Keep the device offroad regardless of ignition."},
    {"key": "DeviceBootMode", "label": "Wake Up Behavior", "panel": "device",
     "section": "General", "type": SettingType.ENUM, "default": 0,
     "options": _opt((0, "Standard"), (1, "Always Offroad")),
     "description": "Device state after boot/sleep."},
    {"key": "QuietMode", "label": "Quiet Mode", "panel": "device", "section": "General",
     "default": False, "description": "Suppress non-critical chimes."},
    {"key": "OnroadUploads", "label": "Onroad Uploads", "panel": "device", "section": "General",
     "default": True, "description": "Allow uploads while onroad."},
    {"key": "LanguageSetting", "label": "Language", "panel": "device", "section": "Language",
     "type": SettingType.ENUM, "default": "en",
     "options": [{"value": "en", "label": "English"}, {"value": "es", "label": "Español"},
                 {"value": "de", "label": "Deutsch"}, {"value": "fr", "label": "Français"},
                 {"value": "ja", "label": "日本語"}],
     "description": "Device UI language."},

    # ---- Software ------------------------------------------------------------------------
    {"key": "DisableUpdates", "label": "Disable Updates", "panel": "software",
     "section": "Updates", "default": False, "requires_offroad": True, "requires_reboot": True,
     "danger": CAUTION, "description": "Turn off automatic software updates (requires reboot)."},

    # ---- Developer -----------------------------------------------------------------------
    {"key": "AdbEnabled", "label": "Enable ADB", "panel": "developer", "section": "Connectivity",
     "default": False, "requires_offroad": True,
     "description": "Allow Android Debug Bridge over USB/network."},
    {"key": "SshEnabled", "label": "Enable SSH", "panel": "developer", "section": "Connectivity",
     "default": False, "description": "Allow SSH access to the device."},
    {"key": "JoystickDebugMode", "label": "Joystick Debug Mode", "panel": "developer",
     "section": "Connectivity", "default": False, "requires_offroad": True, "danger": DANGEROUS,
     "description": "Control the car with a joystick for debugging."},
    {"key": "AlphaLongitudinalEnabled", "label": "sunnypilot Longitudinal Control (Alpha)",
     "panel": "developer", "section": "Connectivity", "default": False, "requires_offroad": True,
     "requires_reboot": True, "danger": DANGEROUS, "capability": "alpha_long_available",
     "description": "WARNING: alpha longitudinal control may disable Automatic Emergency Braking (AEB)."},
    {"key": "ShowDebugInfo", "label": "UI Debug Mode", "panel": "developer",
     "section": "Connectivity", "default": False,
     "description": "Show touches, FPS, and debug overlays."},
    {"key": "LongitudinalManeuverMode", "label": "Longitudinal Maneuver Mode",
     "panel": "developer", "section": "Test Maneuvers", "default": False,
     "requires_offroad": True, "danger": DANGEROUS, "capability": "has_longitudinal_control",
     "description": "Run longitudinal test maneuvers (development)."},
    {"key": "ShowAdvancedControls", "label": "Show Advanced Controls", "panel": "developer",
     "section": "Advanced", "default": False,
     "description": "Reveal advanced sunnypilot controls (visibility only)."},
    {"key": "EnableCopyparty", "label": "copyparty File Server", "panel": "developer",
     "section": "Advanced", "default": False, "danger": CAUTION,
     "description": "Run a file server to download routes / view logs from the device."},
]
