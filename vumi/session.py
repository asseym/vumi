import yaml
import json
import time
import datetime

from vumi.errors import VumiError


class VumiSession():
    key = None
    decision_tree = None

    def __init__(self, **kwargs):
        pass

    def set_decision_tree(self, decision_tree):
        self.decision_tree = decision_tree

    def get_decision_tree(self):
        return self.decision_tree


class DecisionTree():
    pass


class TemplatedDecisionTree(DecisionTree):
    template = None
    template_current = None
    template_history = []

    def load_yaml_template(self, yaml_string):
        self.template = yaml.load(yaml_string)
        self.template_current = self.template.get('__start__')

    def get_template(self):
        return self.template

    def get_data_source(self):
        if self.template:
            if self.template.get('__data__'):
                return {"url"     :self.template['__data__'].get('url'),
                        "username":self.template['__data__'].get('username'),
                        "password":self.template['__data__'].get('password'),
                        "params"  :self.template['__data__'].get('params',[])}
        return {"username":None, "password":None, "url":None, "params":[]}

    def get_post_source(self):
        if self.template:
            if self.template.get('__post__'):
                return {"url"     :self.template['__post__'].get('url'),
                        "username":self.template['__post__'].get('username'),
                        "password":self.template['__post__'].get('password'),
                        "params"  :self.template['__post__'].get('params',[])}
        return {"username":None, "password":None, "url":None, "params":[]}

    def get_dummy_data(self):
        if self.template:
            if self.template.get('__data__'):
                return self.template['__data__'].get('json')
        return None





class PopulatedDecisionTree(TemplatedDecisionTree):
    data = None
    # So that I can modify the original data, data_current must
    # be stored by reference as a list/dict, index/key pair
    data_current = ([None],0)
    data_history = []

    def load_json_data(self, json_string):
        self.data = json.loads(json_string)

    def load_dummy_data(self):
        self.load_json_data(self.get_dummy_data())

    def dump_json_data(self):
        return json.dumps(self.data)

    def get_data(self):
        return self.data

    def resolve_dc(self):
        return self.data_current[0][self.data_current[1]]

    def update_dc(self, new_value):
        self.data_current[0][self.data_current[1]] = new_value


class TraversedDecisionTree(PopulatedDecisionTree):
    echo = False
    started = False
    completed = False
    language = "english"

    # The data will be a nested data-structure of a sort that can
    # be deserialized from a JSON string.

    # This means that when traversing it the current object will be one of:
    #     dict    -> in which case the template should auto-select the correct key
    #     list    -> in which case the user should be asked from displayed options
    #                where there is only one list option it should be auto-selected
    #     boolean -> as for list, just yes/no questions only
    #     number  -> in which case the user should be prompted for a value
    #     string  -> in which case the user should be prompted for text

    # NB. User entered strings (which include things like dates),
        # should be avoided where possible.


    def resolve_default(self, default):
        return default


    def is_completed(self):
        return self.completed

    def is_started(self):
        return self.started

    def echo_on(self):
        self.echo = True

    def set_language(self, language):
        self.language = language


    def dumps(self, level=1, serialize=repr):
        def wrap(title, serialize, obj):
            return "\n****"+str(title)+"****\n" \
                    + serialize(obj)
        s = ""
        if level >= 1:
            s += wrap("TEMPLATE", serialize, self.template)
        if level >= 0:
            s += wrap("TEMPLATE_CURRENT", serialize, self.template_current)
        if level >= 2:
            s += wrap("TEMPLATE_HISTORY", serialize, self.template_history)
        if level >= 1:
            s += wrap("DATA", serialize, self.data)
        if level >= 0:
            s += wrap("DATA_CURRENT", serialize, self.data_current)
        if level >= 2:
            s += wrap("DATA_HISTORY", serialize, self.data_history)
        return s


    def select(self, template, data):
        self.template_history.append(self.template_current)
        self.data_history.append(self.data_current)
        self.template_current = template
        self.data_current = data


    def try_auto_select(self):
        if type(self.resolve_dc()) == list and len(self.resolve_dc())==1:
            __next = self.template_current.get('next')
            d = (self.resolve_dc()[0], __next)
            t = self.template.get(__next)
            self.select(t, d)
            return True
        return False


    def go_back(self):
        try:
            self.template_current = self.template_history.pop()
            self.data_current = self.data_history.pop()
            self.completed = False
        except:
            pass


    def go_up(self):
        old_data_current_0 = self.data_current[0]
        self.go_back()
        while old_data_current_0 == self.data_current[0] \
                and len(self.data_history) > 0:
            self.go_back()


    def start(self):
        self.started = True
        greeting = ''
        if self.template_current.get('display'):
            greeting += self.template_current['display'].get(
                    self.language, '')
        if self.echo:
            print "\n", greeting
        if not self.template:
            raise VumiError("template must be loaded")
        if not self.data:
            raise VumiError("data must be loaded")
        __next = self.template_current.get('next')
        t = self.template.get(__next)
        d = (self.data, __next)
        self.select(t, d)
        return greeting


    def __finish(self):
        self.completed = True

    def finish(self):
        if self.completed:
            goodbye = ''
            if self.template_current.get('display'):
                goodbye += self.template_current['display'].get(
                        self.language, '')
            if self.echo:
                print goodbye
            return goodbye
        else:
            return None


    def question(self):
        self.try_auto_select()
        count = 0
        que = ""
        que += self.template_current['question'][self.language]
        if type(self.resolve_dc()) == list:
            for opt in self.resolve_dc():
                count += 1
                que += "\n" + str(count) + ". "
                que += str(opt.get(self.template_current['options']))
        elif type(self.template_current.get('options')) == list:
            for opt in self.template_current.get('options'):
                count += 1
                que += "\n" + str(count) + ". "
                que += str(opt.get('display').get(self.language))
        if self.echo:
            print que
        return que


    def answer(self, ans):
        try:
            if self.echo:
                print ">", ans, "\n"
            ans = str(ans) # in reality we'll only get text
            ans = self.validate(ans, self.template_current.get('validate'))
            __next = self.template_current.get('next')
            if type(self.resolve_dc()) == list:
                d = (self.resolve_dc()[int(ans)-1], __next)
                t = self.template.get(__next)
            elif type(self.template_current.get('options')) == list:
                opt = self.template_current.get('options')[int(ans)-1]
                __next = opt.get('next')
                if opt.get('default'):
                    self.update_dc(self.resolve_default(opt['default']))
                    t = self.template.get(__next)
                else:
                    t = __next
                d = self.data_current
            else:
                self.update_dc(ans)
                d = (self.data_current[0], __next)
                t = self.template.get(__next)
            self.select(t, d)
            if __next == "__finish__":
                self.__finish()
        except:
            pass


    def validate(self, ans, validate):
        if validate == 'date':
            return str(int(time.mktime(
                datetime.datetime.strptime(ans, '%d/%m/%Y').timetuple())))
        if validate == 'integer':
            return str(int(ans))
        return ans



