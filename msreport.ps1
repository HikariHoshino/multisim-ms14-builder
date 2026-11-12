# 用法：msreport.ps1 <文件.ms14> netlist            输出 Multisim 网表文本（每行：网络 单字母 元件 引脚）
#       msreport.ps1 <文件.ms14> image <输出路径>   导出整页电路图，Multisim 自动补 .png 扩展名
# 结束时只关掉本脚本启动的 Multisim 进程，不碰用户自己开着的窗口。
$before = @(Get-Process multisim -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
try {
    $app = New-Object -ComObject MultisimInterface.MultisimApp
    $app.Connect()
    $c = $app.OpenFile($args[0])
    if ($args[1] -eq "netlist") {
        $n = $c.ReportNetlist($false, 0, $null)
        [string]$n
    } elseif ($args[1] -eq "image") {
        $r = $c.GetCircuitImage(0, $args[2])
        "image -> $r"
    }
    $app.Disconnect()
} finally {
    # 仿真服务进程（/SimServer）会在主进程退出前后才冒出来，隔两秒再查两轮，免得留下孤儿进程
    foreach ($i in 1..3) { Get-Process multisim -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Stop-Process -Force; Start-Sleep 2 }
}
