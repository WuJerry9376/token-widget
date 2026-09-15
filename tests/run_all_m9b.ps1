# M9b 全量回归聚合：逐文件跑 tests\test_*.py，抓尾行「x/y 通过」（数字模式匹配，
# 不注入任何环境变量——PYTHONIOENCODING 会干扰子进程类用例）。
Set-Location "$PSScriptRoot\.."
$total = 0; $passed = 0; $bad = @()
foreach ($f in (Get-ChildItem tests\test_*.py)) {
    python $f.FullName > "$env:TEMP\m9b_test_out.txt" 2>&1
    $code = $LASTEXITCODE
    $lines = Get-Content "$env:TEMP\m9b_test_out.txt" -Encoding UTF8
    $tail = @($lines | Where-Object { $_ -match '^\s*(\d+)\s*/\s*(\d+)' } | Select-Object -Last 1)
    if ($tail.Count -eq 1) {
        $m = [regex]::Match($tail[0], '^\s*(\d+)\s*/\s*(\d+)')
        $p = [int]$m.Groups[1].Value; $t = [int]$m.Groups[2].Value
        $passed += $p; $total += $t
        $flag = if ($code -ne 0 -or $p -ne $t) { '   <== FAIL' } else { '' }
        Write-Host ('{0,-22} {1}/{2}{3}' -f $f.Name, $p, $t, $flag)
        if ($p -ne $t) { $bad += $f.Name; $lines | Where-Object { $_ -match 'FAIL' } | ForEach-Object { Write-Host "   | $_" } }
    } else {
        $bad += $f.Name
        Write-Host ('{0,-22} 无 x/y 尾行 (exit={1})' -f $f.Name, $code)
        $lines | Select-Object -Last 6 | ForEach-Object { Write-Host "   | $_" }
    }
}
Write-Host "TOTAL: $passed/$total"
if ($bad) { Write-Host ("FAILED FILES: " + ($bad -join ', ')); exit 1 } else { exit 0 }
