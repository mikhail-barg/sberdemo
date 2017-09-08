from functools import lru_cache

import pymorphy2
from typing import List, Dict, Callable, Any, Union

from slots import read_slots_from_tsv
from slots_classifier_utlilities import *

# fasttext_file = '/home/marat/data/rusfasttext_on_news/model_yalen_sg_300.bin'
FASTTEXT_MODEL = '/home/marat/data/rusfasttext_on_news/ft_0.8.3_yalen_sg_300.bin'


class Preprocessor:
    def process(self, words: List[Dict]) -> List[Dict]:
        raise NotImplemented()


class Fasttext(Preprocessor):
    def __init__(self, model_path):
        import fasttext
        self.model = fasttext.load_model(model_path)

    def process(self, words: List[Dict]):
        for w in words:
            w['_vec'].append(self.model[w['_text']])
        return words


class PyMorphyPreproc(Preprocessor):
    def __init__(self, vectorize=True):
        self.vectorize = vectorize
        self.morph = pymorphy2.MorphAnalyzer()
        tags = sorted(self.morph.dictionary.Tag.KNOWN_GRAMMEMES)
        self.tagmap = dict(zip(tags, range(len(tags))))

    def process(self, words):
        res = []
        for w in words:
            p = self.morph.parse(w['_text'])
            w['normal'] = p[0].normal_form.replace('ё', 'е')
            v = np.zeros(len(self.tagmap))
            # TODO: Note index getter p[0] -- we need better disambiguation
            for tag in str(p[0].tag).replace(' ', ',').split(','):
                w['t_' + tag] = 1
                v[self.tagmap[tag]] = 1
            if self.vectorize:
                w['_vec'].append(v)
            res.append(w)
        return res


class Lower(Preprocessor):
    def process(self, words):
        res = []
        for w in words:
            w['_text'] = w['_text'].lower()
            res.append(w)
        return res


class PreprocessorPipeline:
    def __init__(self,
                 sent_tokenizer: Callable[[str], List[str]],
                 word_tokenizer: Callable[[str], List[str]],
                 feature_gens: List[Preprocessor],
                 embedder: Callable):
        self.sent_tokenizer = sent_tokenizer
        self.word_tokenizer = word_tokenizer
        self.feature_gens = feature_gens
        self.embedder = embedder

    @lru_cache()
    def feed(self, raw_input: str) -> ('embedding', List[str]):
        # TODO: is it OK to merge words from sentences?
        words = []
        for s in self.sent_tokenizer(raw_input):
            ws = [{'_text': w, '_vec': []} for w in self.word_tokenizer(s)]
            for fg in self.feature_gens:
                ws = fg.process(ws)
            if ws:
                words.extend(ws)

        return self.embedder([w['_vec'] for w in words]), words


if __name__ == '__main__':
    pmp = PyMorphyPreproc(vectorize=False)
    assert pmp.process([{'_text': 'Разлетелся'}, {'_text': 'градиент'}]) == [{'t_intr': 1, 't_VERB': 1, 't_indc': 1,
                                                                              'normal': 'разлететься', 't_past': 1,
                                                                              't_sing': 1, '_text': 'Разлетелся',
                                                                              't_perf': 1, 't_masc': 1},
                                                                             {'t_sing': 1, 't_NOUN': 1,
                                                                              'normal': 'градиент', '_text': 'градиент',
                                                                              't_nomn': 1, 't_inan': 1, 't_masc': 1}]

    lower = Lower()
    assert lower.process([{'_text': 'Разлетелся'}]) == [{'_text': 'разлетелся'}]

    # pipe = Pipeline(sent_tokenize, word_tokenize, [PyMorphyPreproc(), Lower(), Fasttext(FASTTEXT_MODEL)], embedder=np.vstack)
    pipe = PreprocessorPipeline(sent_tokenize, word_tokenize, [PyMorphyPreproc(), Lower()], embedder=np.vstack)
    test_input_str = 'Добрый день! Могу ли я открыть отдельный счет по 275ФЗ и что для этого нужно? '
    emb, text = pipe.feed(test_input_str)

    assert [w['_text'] for w in text] == ['добрый', 'день', '!', 'могу', 'ли', 'я', 'открыть', 'отдельный', 'счет',
                                          'по', '275фз', 'и', 'что', 'для', 'этого', 'нужно', '?']
    assert emb.shape[0] == 17, 120

    slots = read_slots_from_tsv()
    assert len(slots) == 14, len(slots)

    slotmap = {s.id:s for s in slots}

    assert 'евро' in slotmap['currency'].gen_dict
    assert 'библиотека' in slotmap['client_metro'].gen_dict

    # slotmap['client_metro'].infer_from_composional_request(pipe.feed('Есть рядом с метро савеловская какое-нибудь отделение поблизости?')[1])
    slotmap['client_metro'].infer_from_single_slot(pipe.feed('рядом с метро савеловская')[1])

    print('='*30)
    print('compositional infer for "{}"'.format(test_input_str))
    for s in slots:
        try:
            print(s.infer_from_compositional_request(text))
            print('----------')
        except NotImplementedError:
            print('Infer not implemented for slot "{}"'.format(s.id))


