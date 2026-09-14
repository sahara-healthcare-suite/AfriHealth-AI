# Fixture Speech Recognition Benchmark Report

> **Evidence limitation:** This is a reproducible software fixture, not an
> independent audio benchmark. The hypotheses are embedded in
> `benchmark_suite.py`, and the referenced sample audio is not included.
> Do not present these values as production performance or a real model
> ranking.

| Model | Average WER ↓ | Clinical Entity Accuracy ↑ | FAAS Score (dB) ↑ | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Intron Sahara v2.5** | **0.00%** | **100.00%** | **40.0** | Fixture reference |
| OpenAI Whisper (Medium) | 41.74% | 91.67% | 3.42 | Baseline |
| Meta Wav2Vec2 (XLS-R) | 55.70% | 83.33% | 1.75 | Baseline |

### Evaluation Methodology
1. **Word Error Rate (WER)**: Normalized string distance metric (S + D + I) / N.
2. **Clinical Entity Accuracy**: Recall rate of medical terms (symptoms, dosages, diagnoses).
3. **Fairness-Adjusted ASR Score (FAAS)**: Calculated as 10 * log10(Clinical Entity Accuracy / WER).

The separate 15-case clinical validation baseline reported 56.38% mean WER,
44.33% target-term recall, and critical-term misses in 6 cases. That result is
for clinician review only and does not support autonomous clinical use.
