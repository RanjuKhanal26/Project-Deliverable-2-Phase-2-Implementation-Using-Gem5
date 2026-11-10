# low_power_o3.py - Low-power X86 O3CPU with DVFS, clock gating, and power gating.
import argparse
import m5
from m5.objects import *

parser = argparse.ArgumentParser(description="Low-power X86 O3CPU model")
parser.add_argument("--binary", type=str, required=True)
parser.add_argument("--cpu-clock", type=str, default="1GHz")
parser.add_argument("--cpu-voltage", type=str, default="1.0V")
args = parser.parse_args()
# Cache class definitions (L1ICache, L1DCache, L2Cache are not built-in
# SimObjects; they must be defined as subclasses of Cache).
class L1ICache(Cache):
    """Simple L1 instruction cache with default values."""
    size = "32KiB"
    assoc = 4
    tag_latency = 2
    data_latency = 2
    response_latency = 2
    mshrs = 4
    tgts_per_mshr = 20

class L1DCache(Cache):
    """Simple L1 data cache with default values."""
    size = "32KiB"
    assoc = 4
    tag_latency = 2
    data_latency = 2
    response_latency = 2
    mshrs = 4
    tgts_per_mshr = 20

class L2Cache(Cache):
    """Simple L2 cache with default values."""
    size = "256KiB"
    assoc = 8
    tag_latency = 20
    data_latency = 20
    response_latency = 20
    mshrs = 20
    tgts_per_mshr = 12
# 1. System and clock/voltage domains (DVFS infrastructure)
system = System()
system.clk_domain = SrcClockDomain()
system.clk_domain.clock = args.cpu_clock
system.clk_domain.voltage_domain = VoltageDomain()
system.clk_domain.voltage_domain.voltage = args.cpu_voltage

system.mem_mode = "timing"
system.mem_ranges = [AddrRange("512MB")]

# 2. Memory bus (created early: caches, APIC, and system port attach to it)
system.membus = SystemXBar()
system.system_port = system.membus.cpu_side_ports

# 3. Out-of-order CPU with power-state support
system.cpu = DerivO3CPU()
system.cpu.createInterruptController()

# X86 local-APIC wiring (required for X86 SE-mode simulation)
system.cpu.interrupts[0].pio = system.membus.mem_side_ports
system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

# Clock gating: 20 bins between 1 ns and 1 s; power gating after 300 cycles
system.cpu.p_state_clk_gate_min = "1ns"
system.cpu.p_state_clk_gate_max = "1s"
system.cpu.p_state_clk_gate_bins = 20
system.cpu.pwr_gating_latency = 300
system.cpu.power_gating_on_idle = True

# 4. Cache hierarchy
system.cpu.icache = L1ICache(size="32KiB", assoc=4)
system.cpu.icache.cpu_side = system.cpu.icache_port
system.cpu.icache.mem_side = system.membus.cpu_side_ports

system.cpu.dcache = L1DCache(size="32KiB", assoc=4)
system.cpu.dcache.cpu_side = system.cpu.dcache_port
system.cpu.dcache.mem_side = system.membus.cpu_side_ports

system.l2 = L2Cache(size="256KiB", assoc=8)
system.l2.cpu_side = system.cpu.icache.mem_side
system.l2.cpu_side = system.cpu.dcache.mem_side
system.l2.mem_side = system.membus.cpu_side_ports

# 5. Memory controller
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

# 6. Power models in the fixed order ON, CLK_GATED, SRAM_RETENTION, OFF.
#    "0.004 * temp" gives 1.2 W leakage at the default 300 K.
class CpuPowerOn(MathExprPowerModel):
    def __init__(self, cpu_path, **kwargs):
        super().__init__(**kwargs)
        self.dyn = ("voltage * (2 * {}.ipc + "
                    "3 * 0.000000001 * {}.dcache.overall_misses / sim_seconds)"
                    .format(cpu_path, cpu_path))
        self.st = "0.004 * temp"

class CpuPowerClkGated(MathExprPowerModel):
    def __init__(self, cpu_path, **kwargs):
        super().__init__(**kwargs)
        self.dyn = "0"
        self.st = "0.004 * temp"

class CpuPowerSramRetention(MathExprPowerModel):
    def __init__(self, cpu_path, **kwargs):
        super().__init__(**kwargs)
        self.dyn = "0"
        self.st = "0.004 * temp"

class CpuPowerOff(MathExprPowerModel):
    def __init__(self, cpu_path, **kwargs):
        super().__init__(**kwargs)
        self.dyn = "0"
        self.st = "0"

system.cpu.power_state.default_state = "ON"
system.cpu.power_state.pm = [
    CpuPowerOn(system.cpu.path()),
    CpuPowerClkGated(system.cpu.path()),
    CpuPowerSramRetention(system.cpu.path()),
    CpuPowerOff(system.cpu.path()),
]

# 7. Process and simulation (SE mode)
system.workload = SEWorkload.init_compatible(args.binary)
process = Process()
process.cmd = [args.binary]
system.cpu.workload = process
system.cpu.createThreads()

root = Root(full_system=False, system=system)
m5.instantiate()
print("Beginning simulation!")
event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {event.getCause()}")
