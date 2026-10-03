import SwiftUI
import AVKit
import Photos
import UIKit

struct ContentView: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var tab = 0
    @State private var prompt = ""
    @State private var negative = "text, watermark, blur"
    @State private var imageSize = "768x1152"
    @State private var videoPrompt = ""
    @State private var duration = 5
    @State private var mode = "t2v"
    @State private var width = 768
    @State private var height = 1152
    @State private var history: [TaskItem] = []
    @State private var resultImage: URL?
    @State private var message = ""
    @State private var busy = false
    @State private var showSettings = false

    private var api: APIClient { APIClient(settings: settings) }

    var body: some View {
        NavigationStack {
            ZStack {
                Color(red: 0.07, green: 0.065, blue: 0.055).ignoresSafeArea()
                Group {
                    if tab == 0 { imageView }
                    else if tab == 1 { videoView }
                    else { historyView }
                }
            }
            .navigationTitle("ИИ Студия")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                }
                ToolbarItem(placement: .bottomBar) {
                    Picker("Раздел", selection: $tab) {
                        Label("Фото", systemImage: "photo").tag(0)
                        Label("Видео", systemImage: "video").tag(1)
                        Label("История", systemImage: "clock").tag(2)
                    }.pickerStyle(.segmented)
                }
            }
            .sheet(isPresented: $showSettings) { settingsView }
            .task { await refreshHistory() }
        }
        .preferredColorScheme(.dark)
    }

    private var imageView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header("Изображение", "Генерация через твой сервер")
                Text("Промпт").font(.caption).foregroundStyle(.secondary)
                TextEditor(text: $prompt)
                    .frame(minHeight: 150).scrollContentBackground(.hidden).padding(10)
                    .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
                HStack {
                    Text("Размер").font(.caption).foregroundStyle(.secondary)
                    Picker("Размер", selection: $imageSize) {
                        ForEach(["1024x1024","768x1152","1152x768","768x1344","1344x768","1792x1024","1024x1792"], id: \.self) { Text($0).tag($0) }
                    }.pickerStyle(.menu)
                    Spacer()
                }
                TextField("Негативный промпт", text: $negative).textFieldStyle(.roundedBorder)
                Button { Task { await makeImage() } } label {
                    Label(busy ? "Генерация…" : "Создать изображение", systemImage: "sparkles").frame(maxWidth: .infinity)
                }.buttonStyle(.borderedProminent).tint(Color(red: 0.78, green: 0.65, blue: 0.42))
                if let resultImage {
                    AsyncImage(url: resultImage) { phase in
                        if let image = phase.image { image.resizable().scaledToFit().clipShape(RoundedRectangle(cornerRadius: 18)) }
                        else { ProgressView().frame(maxWidth: .infinity, minHeight: 180) }
                    }
                    Button("Сохранить в Фото") { saveImage(url: resultImage) }.buttonStyle(.bordered)
                }
                if !message.isEmpty { messageView }
            }.padding()
        }
    }

    private var videoView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header("Видео", "Создание задачи простого видео")
                TextEditor(text: $videoPrompt)
                    .frame(minHeight: 150).scrollContentBackground(.hidden).padding(10)
                    .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
                Picker("Режим", selection: $mode) {
                    Text("Текст → видео").tag("t2v"); Text("Изображение → видео").tag("i2v")
                    Text("Текст + изображение").tag("ti2vid"); Text("Ключевые кадры").tag("keyframes")
                }.pickerStyle(.segmented)
                Stepper("Длительность: \(duration) сек", value: $duration, in: 5...30)
                HStack {
                    TextField("Ширина", value: $width, format: .number).textFieldStyle(.roundedBorder)
                    TextField("Высота", value: $height, format: .number).textFieldStyle(.roundedBorder)
                }
                Button { Task { await makeVideo() } } label {
                    Label(busy ? "Запуск…" : "Запустить видео", systemImage: "video.badge.plus").frame(maxWidth: .infinity)
                }.buttonStyle(.borderedProminent).tint(Color(red: 0.78, green: 0.65, blue: 0.42))
                if !message.isEmpty { messageView }
                Text("После запуска открой «Историю».").font(.footnote).foregroundStyle(.secondary)
            }.padding()
        }
    }

    private var historyView: some View {
        List {
            Section("Последние задачи") {
                ForEach(history) { task in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(task.creative_name ?? task.task_id).font(.headline)
                            Spacer()
                            Text(task.status ?? "unknown").font(.caption).foregroundStyle(.secondary)
                        }
                        Text(task.idea ?? task.prompt ?? task.manuscript_text ?? "")
                            .font(.footnote).foregroundStyle(.secondary).lineLimit(3)
                        if task.task_type == "simple" {
                            NavigationLink("Открыть видео") {
                                VideoPreview(taskID: task.task_id, settings: settings)
                            }
                        }
                    }.padding(.vertical, 5)
                }
            }
        }.scrollContentBackground(.hidden).refreshable { await refreshHistory() }
    }

    private var settingsView: some View {
        NavigationStack {
            Form {
                Section("API-сервер") {
                    TextField("http://192.168.1.100:8000", text: $settings.serverURL)
                        .textInputAutocapitalization(.never).keyboardType(.URL)
                    Text("На iPhone 127.0.0.1 означает сам iPhone. Используй IP компьютера или публичный HTTPS-адрес сервера.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }.navigationTitle("Настройки")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Готово") { showSettings = false } } }
        }
    }

    private func header(_ title: String, _ subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.largeTitle.bold()); Text(subtitle).foregroundStyle(.secondary)
        }
    }
    private var messageView: some View {
        Text(message).font(.footnote).padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
    }
    private func makeImage() async {
        guard !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { message = "Введите промпт"; return }
        busy = true; defer { busy = false }
        do {
            let id = try await api.generateImage(prompt: prompt, size: imageSize, negative: negative)
            resultImage = try api.imageURL(taskID: id); message = "Изображение готово: \(id)"
            await refreshHistory()
        } catch { message = "Ошибка: \(error.localizedDescription)" }
    }
    private func makeVideo() async {
        guard !videoPrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { message = "Введите промпт"; return }
        busy = true; defer { busy = false }
        do {
            let id = try await api.generateVideo(prompt: videoPrompt, mode: mode, duration: duration, width: width, height: height)
            message = "Задача создана: \(id)"; await refreshHistory()
        } catch { message = "Ошибка: \(error.localizedDescription)" }
    }
    private func refreshHistory() async {
        do { history = try await api.loadTasks() } catch { message = "Сервер недоступен: \(error.localizedDescription)" }
    }
    private func saveImage(url: URL) {
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data, let image = UIImage(data: data) else { return }
            PHPhotoLibrary.requestAuthorization { status in
                guard status == .authorized || status == .limited else { return }
                PHPhotoLibrary.shared().performChanges {
                    PHAssetChangeRequest.creationRequestForAsset(from: image)
                }
            }
        }.resume()
    }
}

struct VideoPreview: View {
    let taskID: String
    let settings: AppSettings
    @State private var player: AVPlayer?
    var body: some View {
        Group {
            if let player { VideoPlayer(player: player).ignoresSafeArea(edges: .bottom) }
            else { ProgressView() }
        }
        .task {
            if let url = try? APIClient(settings: settings).videoURL(taskID: taskID) {
                player = AVPlayer(url: url)
            }
        }
        .navigationTitle("Видео")
    }
}
