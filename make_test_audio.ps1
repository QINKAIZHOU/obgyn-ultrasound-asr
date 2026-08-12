Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice("Microsoft Huihui Desktop")
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("D:\Projects2026\asr\test.wav", $fmt)
$s.Speak("肝脏形态大小正常，包膜光滑，实质回声均匀。胆囊大小约六点五乘三点二厘米，壁光滑，腔内未见明显异常。双肾大小形态正常，肾盂未见分离。甲状腺右侧叶可见一低回声结节，大小约八乘五毫米，边界清晰，内部未见明显血流信号。")
$s.SetOutputToNull()
$s.Dispose()
Write-Output "done"
