import Foundation
import SwiftUI

final class AppSettings: ObservableObject {
    @Published var serverURL: String {
        didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") }
    }
    init() {
        serverURL = UserDefaults.standard.string(forKey: "serverURL") ?? "http://127.0.0.1:8000"
    }
    var baseURL: URL? {
        URL(string: serverURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/")))
    }
}
