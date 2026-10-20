# Unity Editor baseline

- Phase 80 of the macos26 line provisions the Unity Editor (Apple silicon, LTS) at `/Applications/Unity/Hub/Editor/<version>/Unity.app`, linked as `/Applications/Unity.app` and identified as `bundle:com.unity3d.UnityEditor5.x`.
- The required baseline invokes the editor's `Unity -version` with a sixty-second limit. That command answers without a license.
- It does not activate a license, sign in, create or open a project, start batch mode, or build for WebGL. Those need a Unity license, which is a credential and is never in the image.
- This is an installation and startup baseline, not a functional editor test.
