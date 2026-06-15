# Video Encode Planner (Minimal)

Bu repo, GitHub Actions CPU odaklı encode akışı için küçük bir web aracı içerir.

## Özellikler
- Link veya dosya yolu ile video girişi
- Hazır preset + istenirse özel ayar
- Çözünürlük seçimi (1080p / 720p / 480p / source)
- CRF (sahneye göre dinamik bitrate), capped CRF, 2-pass VBR desteği
- Tahmini encode süresi (public/private runner + preset'e göre)
- Encode çalıştırma, çıktı linki ve tarayıcıdan izleme

## Çalıştırma
```bash
python app.py
```

Sonra tarayıcıda:
`http://127.0.0.1:8000`

## Test
```bash
python -m unittest discover -s tests -v
```

## GitHub Actions
Testler `.github/workflows/tests.yml` ile `push` ve `pull_request` olaylarında GitHub üzerinde otomatik çalışır.