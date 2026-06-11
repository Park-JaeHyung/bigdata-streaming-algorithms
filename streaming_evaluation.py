import hashlib
import csv
import sys
import time
from collections import Counter

# =====================================================================
# PHASE 1 & 2: 알고리즘 직접 구현 및 유틸리티
# =====================================================================

class StreamingEvaluator:
    @staticmethod
    def get_hashes(item, num_hashes, max_val):
        """하나의 item에 대해 서로 다른 num_hashes개의 해시 인덱스를 생성 (Salting 방식)"""
        indices = []
        item_str = str(item)
        for i in range(num_hashes):
            # 문자열 뒤에 인덱스 번호를 붙여 매번 다른 해시값 유도
            encoded = (item_str + str(i)).encode('utf-8')
            hash_val = int(hashlib.md5(encoded).hexdigest(), 16)
            indices.append(hash_val % max_val)
        return indices


class BloomFilter:
    def __init__(self, size, num_hashes):
        self.size = size
        self.num_hashes = num_hashes
        # 메모리를 아끼기 위해 파이썬 내장 bytearray 사용
        self.bit_array = bytearray((size + 7) // 8)
        
    def _set_bit(self, index):
        self.bit_array[index // 8] |= (1 << (index % 8))
        
    def _get_bit(self, index):
        return (self.bit_array[index // 8] & (1 << (index % 8))) != 0

    def add(self, item):
        indices = StreamingEvaluator.get_hashes(item, self.num_hashes, self.size)
        for idx in indices:
            self._set_bit(idx)

    def contains(self, item):
        indices = StreamingEvaluator.get_hashes(item, self.num_hashes, self.size)
        return all(self._get_bit(idx) for idx in indices)


class CountMinSketch:
    def __init__(self, width, depth):
        self.width = width
        self.depth = depth
        # 각각 독립된 메모리 주소를 가지도록 List Comprehension으로 2차원 배열 초기화
        self.table = [[0] * width for _ in range(depth)]
        
    def update(self, item, count=1):
        indices = StreamingEvaluator.get_hashes(item, self.depth, self.width)
        for row, col in enumerate(indices):
            self.table[row][col] += count

    def estimate(self, item):
        indices = StreamingEvaluator.get_hashes(item, self.depth, self.width)
        # 충돌로 인한 과다 추정을 최소화하기 위해 각 행의 예측치 중 최솟값(min) 선택
        return min(self.table[row][col] for row, col in enumerate(indices))


# =====================================================================
# PHASE 3: 대용량 데이터 스트리머 Generator
# =====================================================================

def clickstream_streamer(file_path):
    """대용량 TSV 파일을 한 줄씩 메모리에 로드하여 반환하는 Generator"""
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) < 4:
                continue
            
            curr_page = row[1]    # 현재 방문 페이지
            click_count = row[3]  # 이동 횟수
            
            try:
                click_count = int(click_count)
            except ValueError:
                continue  # 헤더 행 등 숫자가 아닌 경우 건너뜀
                
            yield curr_page, click_count


# =====================================================================
# PHASE 4: 메인 실행 및 정확도·메모리·시간 측정 실험
# =====================================================================

if __name__ == "__main__":
    FILE_PATH = "clickstream-zhwiki-2026-05.tsv"
    
    # 과제 요건: 최소 100,000개 이상의 레코드 테스트
    MAX_RECORDS = 200000 
    
    print("=" * 60)
    print(f" 실험 시작 (최대 {MAX_RECORDS:,}개 레코드 처리 예정)")
    print("=" * 60)
    
    # 1. 자료구조 및 정답셋(Ground Truth) 객체 생성
    # 실험용 기본 파라미터 세팅 (보고서 작성 시 이 수치를 바꿔가며 수집)
    bf_size = 500000
    bf_hashes = 5
    
    cms_width = 5000
    cms_depth = 5
    
    bf = BloomFilter(size=bf_size, num_hashes=bf_hashes)
    cms = CountMinSketch(width=cms_width, depth=cms_depth)
    
    ground_truth_set = set()          # Bloom Filter 정답 비교용
    ground_truth_counter = Counter()  # Count-Min Sketch 정답 비교용
    
    # 2. 스트리밍 데이터 처리 및 시간 측정
    stream = clickstream_streamer(FILE_PATH)
    record_idx = 0
    
    start_time = time.perf_counter()
    
    try:
        for page, count in stream:
            if record_idx >= MAX_RECORDS:
                break
                
            # 알고리즘 데이터 입력 업데이트
            bf.add(page)
            cms.update(page, count)
            
            # Ground Truth 데이터 업데이트
            ground_truth_set.add(page)
            ground_truth_counter[page] += count
            
            record_idx += 1
            if record_idx % 50000 == 0:
                print(f" -> 현재 {record_idx:,}개 진행 중...")
                
    except FileNotFoundError:
        print(f"\n[오류] 지정한 경로에 파일이 없습니다: {FILE_PATH}")
        print("다운로드한 실치 파일명을 소스코드 상단 FILE_PATH에 입력했는지 확인해 주세요.")
        sys.exit(1)

    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    
    # =====================================================================
    # PHASE 5: 결과 및 성능 메트릭 출력
    # =====================================================================
    print("\n" + "=" * 60)
    print(" 1. 처리 시간 및 처리량(Throughput) 결과")
    print("=" * 60)
    print(f"[-] 총 처리 데이터 수 : {record_idx:,} 개")
    print(f"[-] 전체 연산 소요 시간 : {elapsed_time:.4f} 초")
    print(f"[-] 초당 데이터 처리량 : {record_idx / elapsed_time:.2f} items/sec")
    
    print("\n" + "=" * 60)
    print(" 2. 메모리 사용량(Memory Usage) 결과")
    print("=" * 60)
    # 자료구조 핵심 내부 배열의 실제 크기 계산
    bf_mem = sys.getsizeof(bf.bit_array)
    cms_mem = sys.getsizeof(cms.table) + sum(sys.getsizeof(row) for row in cms.table)
    gt_set_mem = sys.getsizeof(ground_truth_set)
    gt_dict_mem = sys.getsizeof(ground_truth_counter)
    
    print(f"[-] Bloom Filter 자료구조 메모리      : {bf_mem / 1024:.2f} KB")
    print(f"[-] Count-Min Sketch 자료구조 메모리   : {cms_mem / 1024:.2f} KB")
    print(f"[-] Ground Truth (set) 메모리          : {gt_set_mem / 1024:.2f} KB")
    print(f"[-] Ground Truth (dict) 메모리         : {gt_dict_mem / 1024:.2f} KB")
    print(f"   * 정답셋 대비 근사 알고리즘의 메모리 절약율을 보고서에 비교 명시하세요.")

    print("\n" + "=" * 60)
    print(" 3. 정확도 및 오차율(Accuracy & Error) 결과")
    print("=" * 60)
    
    # (1) Bloom Filter 검증: 실제 등장한 적 없는 단어 10,000개로 False Positive 측정
    test_non_existing = [f"FakeNonExistPageName_{i}" for i in range(10000)]
    false_positives = 0
    for item in test_non_existing:
        if bf.contains(item):  # 없는데 있다고 구라치면 오탐
            false_positives += 1
    fp_rate = (false_positives / len(test_non_existing)) * 100
    print(f"[-] Bloom Filter False Positive Rate : {fp_rate:.4f}%")
    
    # (2) Count-Min Sketch 검증: 실제 존재했던 유니크 페이지들의 오차율 추정
    total_absolute_error = 0
    unique_items = list(ground_truth_set)
    
    for item in unique_items:
        true_val = ground_truth_counter[item]
        est_val = cms.estimate(item)
        total_absolute_error += (est_val - true_val) # CMS 특성상 est >= true
        
    avg_mae = total_absolute_error / len(unique_items)
    print(f"[-] Count-Min Sketch 평균 과다추정 오차 (MAE) : {avg_mae:.4f}")
    print("=" * 60)