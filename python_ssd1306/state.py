# Python SSD1306 OLED驱动程序，I2C接口
import datetime
import os
import subprocess
import time
import framebuf
import smbus

SET_CONTRAST = 0x81
SET_ENTIRE_ON = 0xA4
SET_NORM_INV = 0xA6
SET_DISP = 0xAE
SET_MEM_ADDR = 0x20
SET_COL_ADDR = 0x21
SET_PAGE_ADDR = 0x22
SET_DISP_START_LINE = 0x40
SET_SEG_REMAP = 0xA0
SET_MUX_RATIO = 0xA8
SET_COM_OUT_DIR = 0xC0
SET_DISP_OFFSET = 0xD3
SET_COM_PIN_CFG = 0xDA
SET_DISP_CLK_DIV = 0xD5
SET_PRECHARGE = 0xD9
SET_VCOM_DESEL = 0xDB
SET_CHARGE_PUMP = 0x8D


class _SSD1306(framebuf.FrameBuffer):
    """SSD1306显示驱动器的基类"""

    def __init__(self, buffer, width, height, *, external_vcc, reset):
        super().__init__(buffer, width, height)
        self.width = width
        self.height = height
        self.external_vcc = external_vcc
        self.reset_pin = reset
        if self.reset_pin:
            self.reset_pin.switch_to_output(value=0)
        self.pages = self.height // 8
        # 注意，子类必须将self.framebuf初始化为帧缓冲区。
        # 这是必需的，因为基础数据缓冲区不同
        self._power = False
        self.poweron()
        self.init_display()

    @property
    def power(self):
        """如果显示器当前已打开，则为True，否则为False"""
        return self._power

    def init_display(self):
        """基类初始化显示"""
        for cmd in (
            SET_DISP | 0x00,  # off
            # 地址设定
            SET_MEM_ADDR,
            0x00,  # 水平的
            # 分辨率和布局
            SET_DISP_START_LINE | 0x00,
            SET_SEG_REMAP | 0x01,  # 列地址127映射到SEG0
            SET_MUX_RATIO,
            self.height - 1,
            SET_COM_OUT_DIR | 0x08,  # 从COM [N]扫描到COM0
            SET_DISP_OFFSET,
            0x00,
            SET_COM_PIN_CFG,
            0x02 if self.height == 32 or self.height == 16 else 0x12,
            SET_DISP_CLK_DIV,
            0x80,
            SET_PRECHARGE,
            0x22 if self.external_vcc else 0xF1,
            SET_VCOM_DESEL,
            0x30,
            SET_CONTRAST,
            0xFF,  # 最大
            SET_ENTIRE_ON,  # 输出跟随RAM内容
            SET_NORM_INV,  # 不倒置
            # 电荷泵
            SET_CHARGE_PUMP,
            0x10 if self.external_vcc else 0x14,
            SET_DISP | 0x01,
        ):  # on
            self.write_cmd(cmd)
        if self.width == 72:
            self.write_cmd(0xAD)
            self.write_cmd(0x30)
        self.fill(0)
        self.show()

    def poweroff(self):
        """关闭显示器（看不到任何东西）"""
        self.write_cmd(SET_DISP | 0x00)
        self._power = False

    def contrast(self, contrast):
        """调整对比度 """
        self.write_cmd(SET_CONTRAST)
        self.write_cmd(contrast)

    def invert(self, invert):
        """反转显示屏上的所有像素"""
        self.write_cmd(SET_NORM_INV | (invert & 1))

    def write_framebuf(self):
        """派生类必须实现此"""
        raise NotImplementedError

    def write_cmd(self, cmd):
        """派生类必须实现此"""
        raise NotImplementedError

    def poweron(self):
        "重置设备并打开显示器。"
        if self.reset_pin:
            self.reset_pin.value = 1
            time.sleep(0.001)
            self.reset_pin.value = 0
            time.sleep(0.010)
            self.reset_pin.value = 1
            time.sleep(0.010)
        self.write_cmd(SET_DISP | 0x01)
        self._power = True

    def show(self):
        """更新显示"""
        xpos0 = 0
        xpos1 = self.width - 1
        if self.width == 64:
            # 宽度为64像素的显示器移动32
            xpos0 += 32
            xpos1 += 32
        if self.width == 72:
            # 宽度为72像素的显示器移动28
            xpos0 += 28
            xpos1 += 28
        self.write_cmd(SET_COL_ADDR)
        self.write_cmd(xpos0)
        self.write_cmd(xpos1)
        self.write_cmd(SET_PAGE_ADDR)
        self.write_cmd(0)
        self.write_cmd(self.pages - 1)
        self.write_framebuf()


class SSD1306_I2C(_SSD1306):
    """
    SSD1306的I2C类
    width:物理屏幕的宽度，以像素为单位，
    height:物理屏幕的高度，以像素为单位，
    i2c:使用的i2c外设，
    addr:设备的8位总线地址
    external_vcc:是否连接外部高压源。
    reset:如有需要，DigitalInOut指定复位引脚
    """

    def __init__(
        self, width, height, i2c, *, addr=0x3C, external_vcc=False, reset=None
    ):
        self.i2c = i2c
        self.addr = addr
        self.temp = bytearray(2)
        # 向数据缓冲区添加一个额外的字节以保存I2C数据/命令字节
        # 使用硬件兼容的I2C事务。的内存视图
        # 缓冲区用于从帧缓冲区操作中屏蔽此字节
        # (没有大的内存命中，因为memoryview不会复制到单独的缓冲区).
        self.buffer = bytearray(((height // 8) * width) + 1)
        self.buffer[0] = 0x40  # Set first byte of data buffer to Co=0, D/C=1
        super().__init__(
            memoryview(self.buffer)[1:],
            width,
            height,
            external_vcc=external_vcc,
            reset=reset,
        )

    def write_cmd(self, cmd):
        """
        将指令写入SSD1306
        """
        self.i2c.write_byte_data(self.addr, 0x80, cmd)

    def write_framebuf(self):
        """
        将缓存的写入SSD1306
        """
        for i in self.buffer[1:]:
            self.i2c.write_byte_data (self.addr, 0x40, i)

if __name__=='__main__':
    ip_cmd = "hostname -I | cut -d\' \' -f1"
    cpu_cmd = "top -bn1 | grep Cpu | awk 'NR==1{printf \"Cpu:%s%%\", $2}'"
    mem_cmd = "free -m | awk 'NR==2{printf \"Mem:%s/%sGB\", $3/1000,$2/1000}'"
    disk_cmd = "df -h | awk '$NF==\"/\"{printf \"Disk:%d/%dGB %s\", $3,$2,$5}'"
    temp_cmd = "sensors | awk 'NR==11{printf \"Temp:%s\", $2}'"
    IP = ""
    Disk = ""
    lt = 0
    i2c = smbus.SMBus(7)
    oled = SSD1306_I2C(128, 64, i2c)
    while True:
        ct = int(time.time())
        # Shell scripts for system monitoring from here : https://unix.stackexchange.com/questions/119126/command-to-display-memory-usage-disk-usage-and-cpu-load
        if(ct - lt > 300):
            IP = subprocess.check_output(ip_cmd, shell=True)
            Disk = subprocess.check_output(disk_cmd, shell=True)
            lt = ct
        CPU = subprocess.check_output(cpu_cmd, shell=True)
        MemUsage = subprocess.check_output(mem_cmd, shell=True)
        Temp = subprocess.check_output(temp_cmd, shell=True)
        # Write two lines of text.
        oled.fill(0)
        oled.text("    ROCK 5B STATE", 0, 0, 1)
        oled.text(" " + str(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ct))), 0, 8, 1)
        oled.text(str(CPU).replace('b\'', '').replace('\'', ''), 0, 16, 1)
        oled.text(str(MemUsage).replace('b\'', '').replace('\'', ''), 0, 24, 1)
        oled.text(str(Disk).replace('b\'', '').replace('\'', ''), 0, 32, 1)
        oled.text(str(Temp).replace('b\'', '').replace('\'', '').replace('\\xc2\\xb0C', ''), 0, 40, 1)
        oled.text("Address:" + str(IP).replace('b\'', '').replace('\\n', '').replace('\'', ''), 0, 48, 1)
        # oled.text("Address:" + str(IP).replace('b\'', '').replace('\\n', '').replace('\'', ''), 0, 56, 1)
        # oled.contrast(10)
        oled.show()
        time.sleep(.5)
