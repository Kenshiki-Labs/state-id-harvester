/** Insert a removable opaque audit receipt without decoding or buffering a raster. */
const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++)
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}
export function receiptChunk(receipt: string): Uint8Array {
  const data = new TextEncoder().encode(`Cadastre-Receipt\0${receipt}`);
  const output = new Uint8Array(data.length + 12);
  const view = new DataView(output.buffer);
  view.setUint32(0, data.length);
  output.set([116, 69, 88, 116], 4);
  output.set(data, 8);
  view.setUint32(
    output.length - 4,
    crc32(output.subarray(4, output.length - 4)),
  );
  return output;
}
function pngHeaderStream(
  body: ReadableStream<Uint8Array>,
  receipt?: string,
): ReadableStream<Uint8Array> {
  const prefix = new Uint8Array(33);
  let count = 0;
  let inserted = false;
  return body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        if (inserted) {
          controller.enqueue(chunk);
          return;
        }
        const take = Math.min(33 - count, chunk.length);
        prefix.set(chunk.subarray(0, take), count);
        count += take;
        if (count < 33) return;
        const view = new DataView(prefix.buffer);
        if (
          !SIGNATURE.every((v, i) => prefix[i] === v) ||
          view.getUint32(8) !== 13 ||
          new TextDecoder().decode(prefix.subarray(12, 16)) !== "IHDR" ||
          crc32(prefix.subarray(12, 29)) !== view.getUint32(29)
        )
          throw new Error("invalid_png");
        controller.enqueue(prefix);
        if (receipt) controller.enqueue(receiptChunk(receipt));
        if (chunk.length > take) controller.enqueue(chunk.subarray(take));
        inserted = true;
      },
      flush() {
        if (!inserted) throw new Error("invalid_png");
      },
    }),
  );
}
export function withPngReceipt(
  body: ReadableStream<Uint8Array>,
  receipt: string,
): ReadableStream<Uint8Array> {
  return pngHeaderStream(body, receipt);
}
/** Validate the header before R2 commits the stream; this does not decode IDAT. */
export function validatePngHeader(
  body: ReadableStream<Uint8Array>,
): ReadableStream<Uint8Array> {
  return pngHeaderStream(body);
}
