import Foundation
import Vision
import ImageIO

struct OCRLine: Codable { let text: String; let confidence: Float; let x: Double; let y: Double; let width: Double; let height: Double }
struct OCRResult: Codable { let lines: [OCRLine]; let text: String; let elapsed_ms: Int }
let start = Date()
guard CommandLine.arguments.count > 1 else { exit(2) }
do {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-AU"]
    request.usesLanguageCorrection = true
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let source = CGImageSourceCreateWithURL(url as CFURL, nil)
    let properties = source.flatMap { CGImageSourceCopyPropertiesAtIndex($0, 0, nil) as? [CFString: Any] }
    let orientation = CGImagePropertyOrientation(rawValue: (properties?[kCGImagePropertyOrientation] as? UInt32) ?? 1) ?? .up
    try VNImageRequestHandler(url: url, orientation: orientation).perform([request])
    let lines = (request.results ?? []).compactMap { observation -> OCRLine? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        return OCRLine(text: candidate.string, confidence: candidate.confidence, x: b.minX, y: b.minY, width: b.width, height: b.height)
    }
    let result = OCRResult(lines: lines, text: lines.map(\.text).joined(separator: "\n"), elapsed_ms: Int(Date().timeIntervalSince(start) * 1000))
    FileHandle.standardOutput.write(try JSONEncoder().encode(result))
} catch { fputs("OCR error: \(error)\n", stderr); exit(1) }
