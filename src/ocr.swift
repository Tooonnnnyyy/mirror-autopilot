import Foundation
import Vision
import AppKit

// Usage: swift ocr.swift <image> [query]
// Prints normalized boxes (x,y top-left origin) + text, then for matches a center point.
let path = CommandLine.arguments[1]
let query = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "BOSS"
guard let img = NSImage(contentsOfFile: path),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("ERR: cannot load image"); exit(2)
}
let req = VNRecognizeTextRequest()
req.recognitionLanguages = ["zh-Hans", "en-US"]
req.recognitionLevel = .accurate
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do { try handler.perform([req]) } catch { print("ERR: \(error)"); exit(2) }
let obs = (req.results as? [VNRecognizedTextObservation]) ?? []
for o in obs {
    guard let top = o.topCandidates(1).first else { continue }
    let b = o.boundingBox
    // Vision origin is bottom-left; convert to top-left normalized
    let x = b.origin.x, yTop = 1.0 - (b.origin.y + b.size.height)
    let cx = x + b.size.width / 2.0, cy = yTop + b.size.height / 2.0
    let txt = top.string.replacingOccurrences(of: "\t", with: " ")
    print(String(format: "%.4f\t%.4f\t%.4f\t%.4f\t%@", cx, cy, b.size.width, b.size.height, txt))
}
