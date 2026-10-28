#include "EdgeDrawingAdapter.hpp"
#include "GrabCutAdapter.hpp"
#include "SeedAdapter.hpp"
#include "GraphExtent.hpp"
#include <opencv2/core.hpp>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

template <typename T> void littleEndian(std::ostream& stream, T value) {
  for (std::size_t byte = 0; byte < sizeof(T); ++byte)
    stream.put(static_cast<char>((static_cast<std::uint64_t>(value) >> (8 * byte)) & 255));
}

std::vector<std::uint8_t> read(const char* path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) throw std::invalid_argument("Input unavailable");
  return {std::istreambuf_iterator<char>(stream), {}};
}
void write(const char* path, const std::vector<std::uint8_t>& bytes) {
  std::ofstream stream(path, std::ios::binary);
  stream.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
  stream.flush();
  if (!stream) throw std::runtime_error("Incomplete output");
}

int main(int argc, char** argv) {
  try {
    if (argc == 4 && std::string(argv[1]) == "graph-extent")
      return spatial_parity::graphExtentRepresentable(std::stoi(argv[2]), std::stoi(argv[3])) ? 0 : 1;
    if (argc == 13 && std::string(argv[1]) == "seeds") {
      std::array<spatial_parity::Vertex, 4> quad;
      for (int i = 0; i < 4; ++i) quad[i] = {std::stod(argv[4 + i * 2]), std::stod(argv[5 + i * 2])};
      write(argv[12], spatial_parity::automaticSeeds(quad, std::stoi(argv[2]), std::stoi(argv[3])));
      return 0;
    }
    if (argc == 9 && std::string(argv[1]) == "segment") {
      const auto rgb = read(argv[2]), seeds = read(argv[6]);
      const auto beforeRGB = rgb, beforeSeeds = seeds;
      const auto result = spatial_parity::segment(rgb.data(), rgb.size(), std::stoi(argv[3]),
          std::stoi(argv[4]), std::stoull(argv[5]), seeds);
      if (rgb != beforeRGB || seeds != beforeSeeds) throw std::runtime_error("Input changed");
      write(argv[7], result.labels); write(argv[8], result.component);
      return 0;
    }
    if (argc == 7 && std::string(argv[1]) == "select") {
      const auto labels = read(argv[2]), seeds = read(argv[3]);
      const auto beforeLabels = labels, beforeSeeds = seeds;
      const auto result = spatial_parity::selectCore(labels, seeds, std::stoi(argv[4]), std::stoi(argv[5]));
      if (labels != beforeLabels || seeds != beforeSeeds) throw std::runtime_error("Input changed");
      write(argv[6], result);
      return 0;
    }
    if (argc != 7) throw std::invalid_argument("Expected input RGB, width, height, stride, points output, offsets output");
    std::ifstream input(argv[1], std::ios::binary);
    if (!input) throw std::invalid_argument("Input unavailable");
    const std::vector<std::uint8_t> rgb{std::istreambuf_iterator<char>(input), {}};
    const auto before = rgb;
    const auto width = std::stoi(argv[2]), height = std::stoi(argv[3]);
    const auto stride = std::stoull(argv[4]);
    const auto edges = spatial_parity::detect(rgb.data(), rgb.size(), width, height, stride);
    if (rgb != before) throw std::runtime_error("Source RGB changed");
    std::ofstream points(argv[5], std::ios::binary), offsets(argv[6], std::ios::binary);
    if (!points || !offsets) throw std::runtime_error("Output unavailable");
    for (const auto& point : edges.points) { littleEndian(points, point.x); littleEndian(points, point.y); }
    for (const auto offset : edges.offsets) littleEndian(offsets, offset);
    points.flush(); offsets.flush();
    if (!points || !offsets) throw std::runtime_error("Incomplete output");
    std::cout << edges.points.size() << " points, " << edges.offsets.size() - 1 << " chains\n";
    return 0;
  } catch (const std::exception& failure) {
    std::cerr << failure.what() << '\n';
    return 1;
  }
}
