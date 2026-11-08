# Generates a synthetic talking-head test recording with deliberate mistakes:
# a false start, filler words, a repeated sentence and long pauses. Uses the
# speech engine built into Windows (System.Speech), so no download is needed.
param([string]$OutWav = "$PSScriptRoot\sample_speech.wav")
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = 0
$s.SetOutputToWaveFile($OutWav)
$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.AppendText("Most service businesses lose half their leads because nobody calls them back.")
$p.AppendBreak([TimeSpan]::FromMilliseconds(2500))
$p.AppendText("Today I'm going to show you, um, the booked solid system.")
$p.AppendBreak([TimeSpan]::FromMilliseconds(700))
$p.AppendText("So the first step is. Sorry, let me start that again.")
$p.AppendBreak([TimeSpan]::FromMilliseconds(900))
$p.AppendText("The first step is to answer every new lead within five minutes.")
$p.AppendBreak([TimeSpan]::FromMilliseconds(600))
$p.AppendText("The first step is to answer every new lead within five minutes.")
$p.AppendBreak([TimeSpan]::FromMilliseconds(3000))
$p.AppendText("Uh, the second step is to follow up three times in the first week.")
$p.AppendBreak([TimeSpan]::FromMilliseconds(800))
$p.AppendText("The third step is to ask every happy customer for a review.")
$p.AppendBreak([TimeSpan]::FromMilliseconds(800))
$p.AppendText("If you want the full checklist, click the link below and book a free call.")
$s.Speak($p)
$s.Dispose()
