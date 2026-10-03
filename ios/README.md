# AI Studio for iOS

Native SwiftUI client for the existing FastAPI server.

Open ios/AIStudio/AIStudio.xcodeproj in Xcode, choose an iPhone simulator or connected iPhone, then Build and Run.

In the app Settings, enter the server address reachable from the iPhone, for example http://192.168.1.100:8000. The API key remains on the server.

Implemented:
- image generation
- video task creation
- task history
- image saving to Photos
- video preview
- server address settings

Server endpoints used:
GET /api/tasks
POST /api/image/generate
GET /api/image/{task_id}
POST /api/tasks/simple
GET /api/video/{task_id}

For App Store distribution, use HTTPS and a production server.
