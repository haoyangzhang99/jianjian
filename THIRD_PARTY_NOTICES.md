# Third-party notices

jianjian's own code is MIT-licensed (see [LICENSE](LICENSE)). It bundles one third-party library
and, at setup time, downloads packages and models that keep their own licenses.

## Bundled in this repository

| Component | License | Where |
|---|---|---|
| [pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) by GuanYixuan | Apache-2.0 | `vendor/pyJianYingDraft/`, unmodified, upstream commit `6bb2d06a713f7b58e1375269daec835a03882086`; its license is in `vendor/pyJianYingDraft/LICENSE` |

## Python packages installed by `setup.sh` (not bundled)

| Package | License |
|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (includes the Silero VAD model) | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT |
| [PyAV](https://github.com/PyAV-Org/PyAV) | BSD-3-Clause (its wheels include FFmpeg libraries under the LGPL) |
| [onnxruntime](https://github.com/microsoft/onnxruntime) | MIT |
| [MLX](https://github.com/ml-explore/mlx) and [mlx-lm](https://github.com/ml-explore/mlx-lm) | MIT |
| [transformers](https://github.com/huggingface/transformers), [tokenizers](https://github.com/huggingface/tokenizers), [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 |
| [NumPy](https://numpy.org) | BSD-3-Clause |
| [opencc-python-reimplemented](https://github.com/yichen0831/opencc-python) | Apache-2.0 |
| [jieba](https://github.com/fxsjy/jieba) | MIT |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | BSD-2-Clause |

## FFmpeg

jianjian runs FFmpeg as a separate program and does not include it. The build that
imageio-ffmpeg downloads is configured with `--enable-gpl` (it includes libx264), so that binary
is GPL-licensed. If you redistribute an FFmpeg binary together with jianjian, follow its license.

## Models downloaded by `setup.sh` (not bundled)

| Model | License |
|---|---|
| Whisper large-v3-turbo (OpenAI), CTranslate2 conversion [mobiuslabsgmbh/faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | MIT |
| [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct), 4-bit MLX conversion by mlx-community (16 GB+ RAM) | Apache-2.0 |
| [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct), 4-bit MLX conversion by mlx-community (under 16 GB RAM) | Apache-2.0 |

Qwen2.5-3B is deliberately not used: it is released under the "qwen-research" license, not an
open-source one. If you pass another model with `--mt-model`, check its license yourself.

## Trademarks

Jianying (剪映) and CapCut are trademarks of ByteDance. jianjian is an independent project and is
not affiliated with or endorsed by ByteDance.
