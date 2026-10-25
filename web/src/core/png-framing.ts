/** Constant-memory PNG framing checks; compressed pixel data is never decoded. */
const IEND_CRC = [174, 66, 96, 130];
export class PngFraming {
  private signatureBytes = 0;
  private readonly header = new Uint8Array(8);
  private headerBytes = 0;
  private remaining = 0;
  private chunkType = "";
  private chunks = 0;
  private hasImageData = false;
  private ended = false;
  private readonly endCrc = new Uint8Array(4);

  write(bytes: Uint8Array): void {
    const skip = Math.min(8 - this.signatureBytes, bytes.length);
    this.signatureBytes += skip;
    let cursor = skip;
    while (cursor < bytes.length) {
      if (this.ended) throw new Error("invalid_png");
      if (this.remaining > 0) {
        cursor = this.consumeData(bytes, cursor);
        continue;
      }
      const take = Math.min(8 - this.headerBytes, bytes.length - cursor);
      this.header.set(bytes.subarray(cursor, cursor + take), this.headerBytes);
      this.headerBytes += take;
      cursor += take;
      if (this.headerBytes === 8) this.beginChunk();
    }
  }

  private beginChunk(): void {
    const length = new DataView(this.header.buffer).getUint32(0);
    const type = new TextDecoder().decode(this.header.subarray(4));
    if (length > 0x7fffffff || !/^[A-Za-z]{4}$/.test(type))
      throw new Error("invalid_png");
    if (this.chunks === 0 && (type !== "IHDR" || length !== 13))
      throw new Error("invalid_png");
    if (this.chunks > 0 && type === "IHDR") throw new Error("invalid_png");
    if (type === "IEND" && (length !== 0 || !this.hasImageData))
      throw new Error("invalid_png");
    if (type === "IDAT" && length > 0) this.hasImageData = true;
    this.chunkType = type;
    this.remaining = length + 4;
    this.headerBytes = 0;
    this.chunks++;
  }

  private consumeData(bytes: Uint8Array, cursor: number): number {
    const take = Math.min(this.remaining, bytes.length - cursor);
    if (this.chunkType === "IEND")
      this.endCrc.set(
        bytes.subarray(cursor, cursor + take),
        4 - this.remaining,
      );
    this.remaining -= take;
    if (this.remaining === 0 && this.chunkType === "IEND") {
      if (!IEND_CRC.every((value, index) => this.endCrc[index] === value))
        throw new Error("invalid_png");
      this.ended = true;
    }
    return cursor + take;
  }

  finish(): void {
    if (!this.ended) throw new Error("invalid_png");
  }
}
