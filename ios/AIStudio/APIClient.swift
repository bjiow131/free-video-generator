import Foundation

struct TaskItem: Identifiable, Codable {
    let id: String
    let task_id: String
    let creative_name: String?
    let task_type: String?
    let status: String?
    let prompt: String?
    let idea: String?
    let manuscript_text: String?
    let final_video_file: String?
    let mode: String?
}
struct TasksResponse: Codable { let tasks: [TaskItem] }

enum APIError: LocalizedError {
    case invalidServer
    case server(String)
    case invalidResponse
    var errorDescription: String? {
        switch self {
        case .invalidServer: return "Проверь адрес API-сервера."
        case .server(let message): return message
        case .invalidResponse: return "Сервер вернул неожиданный ответ."
        }
    }
}

final class APIClient {
    private let settings: AppSettings
    private let session = URLSession.shared
    init(settings: AppSettings) { self.settings = settings }

    private func url(_ path: String) throws -> URL {
        guard let base = settings.baseURL else { throw APIError.invalidServer }
        let cleanPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        guard let endpoint = URL(string: cleanPath, relativeTo: base) else {
            throw APIError.invalidServer
        }
        return endpoint
    }

    private func request(_ path: String, method: String = "GET", body: Data? = nil, contentType: String? = nil) async throws -> Data {
        let endpoint = try url(path)
        var req = URLRequest(url: endpoint)
        req.httpMethod = method
        req.timeoutInterval = 120
        if let contentType { req.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        req.httpBody = body
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = obj["detail"] as? String { throw APIError.server(detail) }
            throw APIError.server("HTTP \(http.statusCode)")
        }
        return data
    }

    func loadTasks() async throws -> [TaskItem] {
        let data = try await request("/api/tasks")
        return try JSONDecoder().decode(TasksResponse.self, from: data).tasks
    }

    private func multipart(fields: [(String,String)]) -> (Data,String) {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        for (name,value) in fields {
            body.append(Data("--\(boundary)\r\n".utf8))
            body.append(Data("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        body.append(Data("--\(boundary)--\r\n".utf8))
        return (body, "multipart/form-data; boundary=\(boundary)")
    }

    func generateImage(prompt: String, size: String, negative: String) async throws -> String {
        let (body, type) = multipart(fields: [("prompt",prompt),("size",size),("negative_prompt",negative)])
        let data = try await request("/api/image/generate", method:"POST", body:body, contentType:type)
        guard let obj = try JSONSerialization.jsonObject(with:data) as? [String:Any],
              let id = obj["task_id"] as? String else { throw APIError.invalidResponse }
        return id
    }

    func generateVideo(prompt: String, mode: String, duration: Int, width: Int, height: Int) async throws -> String {
        let (body, type) = multipart(fields: [("prompt",prompt),("mode",mode),("duration",String(duration)),("video_width",String(width)),("video_height",String(height))])
        let data = try await request("/api/tasks/simple", method:"POST", body:body, contentType:type)
        guard let obj = try JSONSerialization.jsonObject(with:data) as? [String:Any],
              let id = obj["task_id"] as? String else { throw APIError.invalidResponse }
        return id
    }

    func imageURL(taskID: String) throws -> URL { try url("/api/image/\(taskID)") }
    func videoURL(taskID: String) throws -> URL { try url("/api/video/\(taskID)") }
}
