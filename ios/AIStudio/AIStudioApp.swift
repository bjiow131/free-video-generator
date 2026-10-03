import SwiftUI

@main
struct AIStudioApp: App {
    @StateObject private var settings = AppSettings()
    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(settings)
        }
    }
}
