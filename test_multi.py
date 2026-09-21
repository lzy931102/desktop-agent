import sys
sys.path.insert(0, r'F:\opencode-workspace')
from test_moving_target import run_one_round, FastIO
import time

io = FastIO()
for i in range(5):
    start = time.time()
    r = run_one_round(8, io, 'no_predict')
    print('Run {}: hits={}/{} rate={:.1%} offset={:.1f}px passed={} time={:.1f}s'.format(
        i+1, r['hits'], r['clicks'], r['hit_rate'], r['avg_offset'], r['passed'], time.time()-start))