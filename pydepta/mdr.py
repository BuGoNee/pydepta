from collections import namedtuple, defaultdict
import copy

from pyquery import PyQuery as pq

from pydepta.trees import SimpleTreeMatch, tree_depth, PartialTreeAligner, SimpleTreeAligner, tree_size


GeneralizedNode = namedtuple('GeneralizedNode', ['element', 'length'])

class Region(object):
    def __init__(self, **dict):
        self.__dict__.update(dict)
        self._records = []
        self._fields = []

    def __str__(self):
        return "Region: parent {}, start {}, k {},  covered {}, " \
               "parent's size {}".format(self.parent, self.start, self.k, self.covered, len(self.parent))

    def iter(self, k):
        """
        >>> root = [1, 2, 3, 4, 5]
        >>> region = Region(parent=root, start=1, k=1, covered=4)
        >>> list(region.iter(1))
        [[2], [3], [4], [5]]

        >>> region = Region(parent=root, start=1, k=2, covered=4)
        >>> list(region.iter(2))
        [[2, 3], [4, 5]]

        >>> region = Region(parent=root, start=1, k=1, covered=4)
        >>> list(region.iter(2))
        [[2, 3], [4, 5]]

        """
        for i in xrange(self.start, self.start + self.covered, k):
            yield self.parent[i:i + k]

    def elements(self):
        for element in self.iter(1):
            yield element[0]

class Record(object):
    def __init__(self, *elements):
        self.elements = elements

    def __len__(self):
        return len(self.elements)

    def __str__(self):
        return 'DataRecord: %s' % ", ".join('<%s #%s .%s>' %(e.tag, e.get('class') or '', e.get('id') or '') for e in self.elements)

    def __iter__(self):
        return iter(self.elements)

    def __getitem__(self, item):
        return self.elements[item]

    @staticmethod
    def size(record):
        s = 0
        for element in record.elements:
            s += tree_size(element)
        return s

def pairwise(a, K, start=0):
    """
    A generator to return the comparison pair.

    for example:
    >>> list(pairwise([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 3))
    [([1], [2]), ([2], [3]), ([3], [4]), ([4], [5]), ([5], [6]), ([6], [7]), ([7], [8]), ([8], [9]), ([9], [10]), ([1, 2], [3, 4]), ([3, 4], [5, 6]), ([5, 6], [7, 8]), ([7, 8], [9, 10]), ([1, 2, 3], [4, 5, 6]), ([4, 5, 6], [7, 8, 9])]
    >>> list(pairwise([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 2))
    [([1], [2]), ([2], [3]), ([3], [4]), ([4], [5]), ([5], [6]), ([6], [7]), ([7], [8]), ([8], [9]), ([9], [10]), ([1, 2], [3, 4]), ([3, 4], [5, 6]), ([5, 6], [7, 8]), ([7, 8], [9, 10])]
    >>> list(pairwise([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 3, 1))
    [([2], [3]), ([3], [4]), ([4], [5]), ([5], [6]), ([6], [7]), ([7], [8]), ([8], [9]), ([9], [10]), ([2, 3], [4, 5]), ([4, 5], [6, 7]), ([6, 7], [8, 9]), ([2, 3, 4], [5, 6, 7]), ([5, 6, 7], [8, 9, 10])]
    """
    for k in xrange(1, K + 1):
        for i in xrange(start, len(a), k):
            slice_a = a[i:i + k]
            slice_b = a[i + k: i + 2 * k]

            if len(slice_a) >= k and len(slice_b) >= k:
                yield slice_a, slice_b

class MiningDataRegion(object):
    def __init__(self, root, max_generalized_nodes=3, threshold=0.7):
        self.root = root
        self.max_generalized_nodes = max_generalized_nodes
        self.threshold = threshold
        self.stm = SimpleTreeMatch()

    def find_regions(self, root):
        data_regions = []
        if tree_depth(root) >= 2:
            scores = self.compare_generalized_nodes(root, self.max_generalized_nodes)
            data_regions.extend(self.identify_regions(0, root, self.max_generalized_nodes, self.threshold, scores))
            covered = set()
            for data_region in data_regions:
                for i in xrange(data_region.start, data_region.covered):
                    covered.add(data_region.parent[i])

            for child in root:
                if child not in covered:
                    data_regions.extend(self.find_regions(child))
        return data_regions


    def identify_regions(self, start, root, max_generalized_nodes, threshold, scores):
        cur_region = Region(parent=root, start=0, k=0, covered=0)
        max_region = Region(parent=root, start=0, k=0, covered=0)
        data_regions = []

        for k in xrange(1, max_generalized_nodes + 1):
            for i in xrange(start, k + start):
                flag = True
                for j in xrange(i, len(root) - k, k):
                    pair = GeneralizedNode(root[j], k), GeneralizedNode(root[j + k], k)
                    score = scores.get(pair)
                    if score >= threshold:
                        if flag:
                            cur_region.k = k
                            cur_region.start = j
                            cur_region.covered = 2 * k
                            flag = False
                        else:
                            cur_region.covered += k
                    elif not flag:  # doesn't match but previous match
                        break
                if max_region.covered <= cur_region.covered and (
                        max_region.start == 0 or cur_region.start <= max_region.start):
                    max_region.k = cur_region.k
                    max_region.start = cur_region.start
                    max_region.covered = cur_region.covered

        if max_region.covered:
            data_regions.append(max_region)
            if max_region.start + max_region.covered < len(max_region.parent):
                data_regions.extend(self.identify_regions(max_region.start + max_region.covered, root,
                                                          max_generalized_nodes, threshold, scores))

        return data_regions


    def compare_generalized_nodes(self, parent, k):
        """
         compare the adjacent children generalized nodes similarity of a given element

         Arguments:
         `parent`: the lxml element to compare children of.
         `k`: the maximum length of generalized node.
        """
        scores = {}
        for a, b in pairwise(parent, k):
            score = self.stm.normalized_match_score(a, b)
            gn1 = GeneralizedNode(a[0], len(a))
            gn2 = GeneralizedNode(b[0], len(b))
            scores.setdefault((gn1, gn2), score)
        return scores


class MiningDataRecord(object):
    """
    mining the data record from a region.

    basic assumption:
    the subtree of data records also similar. so if not any adjacent pair of them are
    similar (less than threshold), data region itself is a data record,
    otherwise children are individual data record.
    """

    def __init__(self, threshold=0.7):
        self.stm = SimpleTreeMatch()
        self.threshold = threshold

    def find_records(self, region):
        records = []
        if region.k == 1:
            for i in xrange(region.start, region.start + region.covered):
                for child1, child2 in pairwise(region.parent, 1, region.start):
                    similarity = self.stm.normalized_match_score(child1, child2)
                    if similarity < self.threshold:
                        return self.slice_region(region)
                else:
                    # each child of generalized node is a data record
                    for gn in region.iter(1):
                        records.extend([Record(c) for c in gn])

        return self.slice_region(region)

    def slice_region(self, region):
        """
        slice every generalized node of region to a data record
        """
        records = []
        for gn in region.iter(region.k):
            elements = [element for element in gn]
            records.append(Record(*elements))
        return records

class MiningDataField(object):
    """
    Mining the data item from data records with partial tree alignment.
    """
    def __init__(self):
        self.pta = PartialTreeAligner(SimpleTreeAligner())

    def align_records(self, records):
        """
        partial align multiple records.

        for example (from paper Web Data Extraction Based on Partial Tree Alignment):
        >>> from lxml.html import fragment_fromstring
        >>> t1 = fragment_fromstring("<p> <x1></x1> <x2></x2> <x3></x3> <x></x> <b></b> <d></d> </p>")
        >>> t2 = fragment_fromstring("<p> <b></b> <n></n> <c></c> <k></k> <g></g> </p>")
        >>> t3 = fragment_fromstring("<p> <b></b> <c></c> <d></d> <h></h> <k></k> </p>")
        >>> mdf = MiningDataField()
        >>> _, seed = mdf.align_records([Record(t1), Record(t2), Record(t3)])
        >>> [e.tag for e in seed[0]]
        ['x1', 'x2', 'x3', 'x', 'b', 'n', 'c', 'd', 'h', 'k', 'g']
        >>> [e.tag for e in t1]
        ['x1', 'x2', 'x3', 'x', 'b', 'd']
        """
        # sort by the tree size
        sorted_records = sorted(records, key=Record.size)

        # seed is the largest tree
        seed = sorted_records.pop()

        # a dict like {'t2': {}, 't3': {}, etc}
        # the nested dictionary is like {'seed_element' : 'original_element'}
        mappings = defaultdict(dict)
        seed_copy = copy.deepcopy(seed)
        mappings.setdefault(seed, self._create_seed_mapping(seed_copy, seed))

        R = []
        items = []
        while len(sorted_records):
            next = sorted_records.pop()
            modified, partial_match, aligned = self.pta.align(seed_copy, next)
            if modified:
                mappings.update({next: aligned})
                sorted_records.extend(R)
                R = []
            else:
                # add it back to try it later since seed might change
                if partial_match:
                    R.append(next)
                else:
                    mappings.update({next: aligned})

        for record in records:
            aligned = mappings[record]
            items.append(self._extract_item(seed_copy, aligned))

        return items, seed_copy

    def _create_seed_mapping(self, seed, record):
        """
        create a mapping from seed record to data record.

        for example:
        >>> from lxml.html import fragment_fromstring
        >>> t1 = fragment_fromstring("<p id='1'> <a></a> <b></b> </p>")
        >>> d1 = Record(t1)
        >>> p1 = t1

        >>> t2 = fragment_fromstring("<p id='2'> <a></a> <b></b> </p>")
        >>> d2 = Record(t2)
        >>> p2 = t2

        >>> mdr = MiningDataField()
        >>> d = mdr._create_seed_mapping(d1, d2)
        >>> d[p1] == p2
        True

        """
        d = {}
        for s, e in zip(seed, record):
            d[s] = e
            d.update(self._create_seed_mapping(s, e))
        return d

    def _extract_item(self, seed, d):
        """
        extract data item from the tree.
        `seed`: the seed tree
        `d`: a seed element -> original element dictionary
        """
        from pydepta.depta import Item
        fields = self._extract_field(seed, d)
        return Item(fields)

    def _extract_field(self, seed, record):
        r = []
        from pydepta.depta import Field
        for s in seed:
            e = record.get(s, None)
            if e is not None:
                field = Field(pq(e).text(), pq(e).html())
                r.append(field)
        return r