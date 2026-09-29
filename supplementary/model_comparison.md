# Camera-ready score summary

Reference: 74 semantic / 286 non-semantic records; the rule-written synthetic arm contains 104 errors / 255 controls.

| Model | Condition | n | P | R | F1 | kappa |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Claude Haiku 4.5 | assisted | 360 | 0.4207 | 0.9324 | 0.5798 | 0.4138 |
| Claude Haiku 4.5 | detection | 360 | 0.2391 | 0.4459 | 0.3113 | 0.0597 |
| Claude Haiku 4.5 | detection-context | 360 | 0.3431 | 0.4730 | 0.3977 | 0.2093 |
| Claude Haiku 4.5 | assisted-nocomments | 359 | 0.3750 | 0.9730 | 0.5414 | 0.3471 |
| Claude Haiku 4.5 | detection-synthetic | 359 | 0.6335 | 0.9808 | 0.7698 | 0.6448 |
| Claude Sonnet 5 | assisted | 360 | 0.5581 | 0.9730 | 0.7094 | 0.6066 |
| Claude Sonnet 5 | detection | 360 | 0.7000 | 0.3784 | 0.4912 | 0.4055 |
| Claude Sonnet 5 | detection-context | 360 | 0.7111 | 0.4324 | 0.5378 | 0.4527 |
| Claude Sonnet 5 | assisted-nocomments | 360 | 0.4800 | 0.9730 | 0.6429 | 0.5072 |
| Claude Sonnet 5 | detection-synthetic | 359 | 0.9619 | 0.9712 | 0.9665 | 0.9528 |
| Claude Opus 5 | assisted | 360 | 0.6316 | 0.9730 | 0.7660 | 0.6882 |
| Claude Opus 5 | detection | 360 | 0.6667 | 0.2973 | 0.4112 | 0.3257 |
| Claude Opus 5 | detection-context | 360 | 0.6481 | 0.4730 | 0.5469 | 0.4518 |
| Claude Opus 5 | assisted-nocomments | 360 | 0.5625 | 0.9730 | 0.7129 | 0.6117 |
| Claude Opus 5 | detection-synthetic | 359 | 0.9905 | 1.0000 | 0.9952 | 0.9933 |
| Claude Fable 5 | assisted | 360 | 0.6796 | 0.9459 | 0.7910 | 0.7252 |
| Claude Fable 5 | detection | 360 | 0.6129 | 0.5135 | 0.5588 | 0.4571 |
| Claude Fable 5 | detection-context | 360 | 0.5541 | 0.5541 | 0.5541 | 0.4387 |
| Claude Fable 5 | assisted-nocomments | 360 | 0.5882 | 0.9459 | 0.7254 | 0.6321 |
| Claude Fable 5 | detection-synthetic | 359 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| GPT-5.6 Terra Pro | assisted | 360 | 0.4722 | 0.9189 | 0.6239 | 0.4836 |
| GPT-5.6 Terra Pro | detection | 360 | 0.4444 | 0.4865 | 0.4645 | 0.3180 |
| GPT-5.6 Terra Pro | detection-context | 360 | 0.4875 | 0.5270 | 0.5065 | 0.3725 |
| GPT-5.6 Terra Pro | assisted-nocomments | 360 | 0.3777 | 0.9595 | 0.5420 | 0.3503 |
| GPT-5.6 Terra Pro | detection-synthetic | 359 | 0.9358 | 0.9808 | 0.9577 | 0.9399 |
| Gemini 3.1 Pro | assisted | 351 | 0.4783 | 0.9565 | 0.6377 | 0.5090 |
| Gemini 3.1 Pro | detection | 342 | 0.4430 | 0.4730 | 0.4575 | 0.3014 |
| Gemini 3.1 Pro | detection-synthetic | 352 | 0.8534 | 1.0000 | 0.9209 | 0.8865 |
| Kimi K3 | assisted | 360 | 0.6632 | 0.8514 | 0.7456 | 0.6691 |
| Kimi K3 | detection | 360 | 0.5410 | 0.4459 | 0.4889 | 0.3723 |
| Kimi K3 | detection-context | 360 | 0.4512 | 0.5000 | 0.4744 | 0.3295 |
| Kimi K3 | assisted-nocomments | 360 | 0.5379 | 0.9595 | 0.6893 | 0.5782 |
| Kimi K3 | detection-synthetic | 359 | 0.9369 | 1.0000 | 0.9674 | 0.9535 |
| Muse Spark 1.2 | assisted | 0 | -- | -- | -- | -- |
| Muse Spark 1.2 | detection | 0 | -- | -- | -- | -- |
| Muse Spark 1.2 | detection-synthetic | 0 | -- | -- | -- | -- |
| DeepSeek V4 Pro | assisted | 360 | 0.4207 | 0.9324 | 0.5798 | 0.4138 |
| DeepSeek V4 Pro | detection | 360 | 0.3525 | 0.5811 | 0.4388 | 0.2458 |
| DeepSeek V4 Pro | detection-synthetic | 359 | 0.6000 | 0.9519 | 0.7361 | 0.5905 |
| Qwen 3.8 Max | assisted | 328 | 0.4574 | 0.9672 | 0.6211 | 0.4930 |
| Qwen 3.8 Max | detection | 335 | 0.4235 | 0.5455 | 0.4768 | 0.3277 |
| Qwen 3.8 Max | detection-synthetic | 0 | -- | -- | -- | -- |
| Grok 4.6 | assisted | 360 | 0.5263 | 0.9459 | 0.6763 | 0.5601 |
| Grok 4.6 | detection | 360 | 0.4000 | 0.5676 | 0.4693 | 0.3006 |
| Grok 4.6 | detection-context | 360 | 0.4271 | 0.5541 | 0.4824 | 0.3258 |
| Grok 4.6 | assisted-nocomments | 360 | 0.4459 | 0.9459 | 0.6061 | 0.4533 |
| Grok 4.6 | detection-synthetic | 359 | 0.9018 | 0.9712 | 0.9352 | 0.9074 |
| GLM 5.3 | assisted | 328 | 0.4014 | 0.9219 | 0.5592 | 0.3947 |
| GLM 5.3 | detection | 319 | 0.4308 | 0.4308 | 0.4308 | 0.2851 |
| GLM 5.3 | detection-synthetic | 37 | 0.7692 | 0.9091 | 0.8333 | 0.7542 |
