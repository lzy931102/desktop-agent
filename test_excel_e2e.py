# -*- coding: utf-8 -*-
"""
P2-1 Excel E2E 测试

用 COM 接口操作 WPS 表格，完成：
1. 打开 Excel
2. 输入数据（A1=10, A2=20, A3==A1+A2）
3. 验证 A3=30
4. 保存到 E:\agent_test\excel_result.xlsx
5. 关闭
"""

import time
import os
import sys

try:
    import win32com.client
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pywin32", "-q"])
    import win32com.client

SAVE_PATH = r"E:\agent_test\excel_result.xlsx"

def main():
    total_start = time.time()
    
    print("=" * 60, flush=True)
    print("WPS Excel E2E Test (COM)", flush=True)
    print("=" * 60, flush=True)
    
    excel = None
    
    try:
        # Step 1: 启动WPS
        t = time.time()
        excel = win32com.client.Dispatch("Ket.Application")
        excel.Visible = True
        time.sleep(2)
        print(f"[Step 1] 启动WPS              {time.time()-t:.2f}s", flush=True)
        
        # Step 2: 新建工作簿
        t = time.time()
        wb = excel.Workbooks.Add()
        ws = wb.ActiveSheet
        time.sleep(1)
        print(f"[Step 2] 新建工作簿            {time.time()-t:.2f}s", flush=True)
        
        # Step 3: A1=10
        t = time.time()
        ws.Range("A1").Value = 10
        print(f"[Step 3] A1=10                {time.time()-t:.2f}s", flush=True)
        
        # Step 4: A2=20
        t = time.time()
        ws.Range("A2").Value = 20
        print(f"[Step 4] A2=20                {time.time()-t:.2f}s", flush=True)
        
        # Step 5: A3=公式
        t = time.time()
        ws.Range("A3").Formula = "=A1+A2"
        print(f"[Step 5] A3==A1+A2            {time.time()-t:.2f}s", flush=True)
        
        # Step 6: 读取验证
        t = time.time()
        a3_val = ws.Range("A3").Value
        print(f"[Step 6] A3计算结果={a3_val}      {time.time()-t:.2f}s", flush=True)
        
        # Step 7: 保存
        t = time.time()
        os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)
        wb.SaveCopyAs(SAVE_PATH)
        print(f"[Step 7] 保存文件              {time.time()-t:.2f}s", flush=True)
        
        # Step 8: 关闭
        t = time.time()
        wb.Close(SaveChanges=False)
        excel.Quit()
        print(f"[Step 8] 关闭WPS              {time.time()-t:.2f}s", flush=True)
        
        # Step 9: 验证
        t = time.time()
        exists = os.path.exists(SAVE_PATH)
        size = os.path.getsize(SAVE_PATH) if exists else 0
        print(f"[Step 9] 文件验证: {exists}, {size}B  {time.time()-t:.2f}s", flush=True)
        
        total_time = time.time() - total_start
        
        print("\n" + "=" * 60, flush=True)
        print(f"总耗时: {total_time:.2f}s", flush=True)
        print(f"A3值: {a3_val}", flush=True)
        print(f"文件: {SAVE_PATH}", flush=True)
        print(f"存在: {exists}, 大小: {size}B", flush=True)
        
        passed = exists and size > 0 and a3_val == 30 and total_time < 60
        print(f"\n{'✓ TEST PASSED' if passed else '✗ TEST FAILED'}", flush=True)
        return passed
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}", flush=True)
        try:
            if excel: excel.Quit()
        except: pass
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
