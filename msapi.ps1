# 用法：msapi.ps1 <输入.ms14> <输出.ms14> <替换表.txt>
# 替换表每行：占位名|section|组|系列|型号，例如 P1||TTL|74LS|74LS153N
# 结束时只关掉本脚本启动的 Multisim 进程，不碰用户自己开着的窗口。
$before = @(Get-Process multisim -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$app = New-Object -ComObject MultisimInterface.MultisimApp
$app.Connect()
$c = $app.OpenFile($args[0])
foreach ($line in Get-Content $args[2]) {
    if (-not $line.Trim()) { continue }
    $f = $line.Split('|')
    $r = $c.ReplaceComponent($f[0], $f[1], 0, $f[2], $f[3], $f[4], "")
    "$($f[0]) -> $r"
}
$c.SaveAs($args[1])
$names = $c.EnumComponents(0)
$names
$app.Disconnect()
# 仿真服务进程（/SimServer）会在主进程退出前后才冒出来，隔两秒再查两轮，免得留下孤儿进程
foreach ($i in 1..3) { Get-Process multisim -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Stop-Process -Force; Start-Sleep 2 }
