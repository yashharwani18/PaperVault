[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Source,[Parameter(Mandatory=$true)][string]$Output,[Parameter(Mandatory=$true)][string]$Result)
$ErrorActionPreference='Stop'
$presentation=$null;$application=$null;$oldSecurity=$null
$existing=@(Get-Process POWERPNT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
try{
 $application=New-Object -ComObject PowerPoint.Application
 $oldSecurity=$application.AutomationSecurity
 $application.AutomationSecurity=3
 # Open a read-only, windowless copy. Macro-enabled formats are not accepted.
 $presentation=$application.Presentations.Open([IO.Path]::GetFullPath($Source),-1,0,0)
 $slides=$presentation.Slides.Count
 # PowerPoint can omit hidden slides despite PrintHiddenSlides in COM export.
 # Unhide only this read-only in-memory copy; the source is never saved.
 for($number=1;$number -le $slides;$number++){$presentation.Slides.Item($number).SlideShowTransition.Hidden=0}
 # PDF, print quality, no frames, slides output, include hidden slides. A physical
 # PDF page must retain the same number as its original PowerPoint slide.
 $range=$presentation.PrintOptions.Ranges.Add(1,$slides)
 $presentation.ExportAsFixedFormat([IO.Path]::GetFullPath($Output),2,2,0,1,1,-1,$range,1,'',$true,$true,$true,$true,$false)
 @{slides=$slides;converter='Microsoft PowerPoint';hidden_slides_included=$true}|ConvertTo-Json|Set-Content -LiteralPath $Result -Encoding utf8
}finally{
 if($presentation){$presentation.Saved=-1;$presentation.Close();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation)}
 if($application){
  if($null -ne $oldSecurity){$application.AutomationSecurity=$oldSecurity}
  # Never close an existing user PowerPoint session.
  if($existing.Count -eq 0){$application.Quit()}
  [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
 }
 [GC]::Collect();[GC]::WaitForPendingFinalizers()
}
