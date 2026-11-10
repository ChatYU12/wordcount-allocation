// 用 macOS Vision 框架做中文 OCR，输出纯文本到 stdout。
// 用法：swift ocr.swift <图片路径>
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("用法: swift ocr.swift <图片路径>\n".data(using: .utf8)!)
    exit(2)
}
let path = args[1]
guard let img = NSImage(contentsOfFile: path),
      let tiff = img.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cg = bitmap.cgImage else {
    FileHandle.standardError.write("无法读取图片: \(path)\n".data(using: .utf8)!)
    exit(3)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
request.recognitionLanguages = ["zh-Hans", "en-US"]

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write("OCR 失败: \(error)\n".data(using: .utf8)!)
    exit(4)
}

guard let observations = request.results else { exit(0) }
// 输出「中心x 	 中心y 	 文字」，坐标为归一化值（原点左下）。
// 版式还原交给调用方按 y 聚类成行，比 Vision 自带的顺序可靠。
for obs in observations {
    if let top = obs.topCandidates(1).first {
        let bb = obs.boundingBox
        let cx = bb.midX
        let cy = bb.midY
        print(String(format: "%.4f\t%.4f\t%@", cx, cy, top.string))
    }
}
