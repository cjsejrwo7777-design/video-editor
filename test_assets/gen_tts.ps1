Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Heami Desktop")
$outPath = Join-Path $PSScriptRoot "speech.wav"
$synth.SetOutputToWaveFile($outPath)

$ssml = @"
<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='ko-KR'>
  <voice name='Microsoft Heami Desktop'>
    안녕하세요, 이것은 자동 영상 편집기 테스트입니다.
    <break time='1200ms'/>
    지금부터 무음 구간을 길게 넣어 보겠습니다.
    <break time='2000ms'/>
    이 구간은 잘려 나가야 합니다.
    <break time='300ms'/>
    이 부분은 짧은 쉼표라서 자연스럽게 남아 있어야 합니다.
    <break time='1800ms'/>
    마지막 문장입니다. 감사합니다.
  </voice>
</speak>
"@

$synth.SpeakSsml($ssml)
$synth.SetOutputToDefaultAudioDevice()
Write-Output "Saved: $outPath"
