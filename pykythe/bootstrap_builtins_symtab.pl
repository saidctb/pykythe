% -*- mode: Prolog -*-

%% File used to bootstrap builtins_symtab.pl

%% In theory, this could be generated by iterating the bootstrap code
%% to a fixed point.

:- encoding(utf8).

:- set_prolog_flag(autoload, false).

builtins_version('${VERSION}').

%% TODO: for Python 2: basestring, unicode, long, xrange, buffer (is this all?)
%% These facts are hand-built from typeshed/stdlib/2and3/builtins.pyi
builtins_symtab_primitive('False',    [class_type('${BUILTINS_FQN}.builtins.bool',     [])]).
builtins_symtab_primitive('None',     [class_type('${BUILTINS_FQN}.builtins.NoneType', [])]).
builtins_symtab_primitive('NoneType', []).
builtins_symtab_primitive('True',     [class_type('${BUILTINS_FQN}.builtins.bool',     [])]).
builtins_symtab_primitive('bool',     [class_type('${BUILTINS_FQN}.builtins.bool',     [[class_type('${BUILTINS_FQN}.builtins.int',[])]])]).
builtins_symtab_primitive('bytes',    [class_type('${BUILTINS_FQN}.builtins.bytes',    [])]). % ByteString
builtins_symtab_primitive('complex',  [class_type('${BUILTINS_FQN}.builtins.complex',  [])]).
builtins_symtab_primitive('dict',     [class_type('${BUILTINS_FQN}.builtins.dict',     [])]). % MutableMapping[_KT, _VT], Generic[_KT, _VT]):
builtins_symtab_primitive('float',    [class_type('${BUILTINS_FQN}.builtins.float',    [])]).
builtins_symtab_primitive('function', [class_type('${BUILTINS_FQN}.builtins.function', [])]).
builtins_symtab_primitive('int',      [class_type('${BUILTINS_FQN}.builtins.int',      [])]).
builtins_symtab_primitive('list',     [class_type('${BUILTINS_FQN}.builtins.list',     [])]). % MutableSequence[_T], Generic[_T]):
builtins_symtab_primitive('object',   [class_type('${BUILTINS_FQN}.builtins.object',   [])]).
builtins_symtab_primitive('set',      [class_type('${BUILTINS_FQN}.builtins.set',      [])]). % MutableSet[_T], Generic[_T]):
builtins_symtab_primitive('str',      [class_type('${BUILTINS_FQN}.builtins.str',      [])]). % Sequence[str], _str_base):
builtins_symtab_primitive('type',     [class_type('${BUILTINS_FQN}.builtins.type',     [])]).

builtins_pairs(Pairs) :-
    setof(Name-Type, builtins_symtab_primitive(Name, Type), Pairs).

builtins_symtab_modules(Symtab) :-
    symtab_empty(Symtab).

builtins_symtab(Symtab) :-
    builtins_pairs(Pairs),
    ord_list_to_symtab(Pairs, Symtab),
    symtab_pairs(Symtab, Pairs).


% %% DO NOT SUBMIT -- these should be from module(pykythe_symtab) but
% %%                  that requires changing the bootstrap process.

% symtab_empty(Symtab) :-
%     Symtab = symtab{}.

% ord_list_to_symtab(Pairs, Symtab) :-
%     dict_pairs(Symtab, symtab, Pairs).

% symtab_pairs(Symtab, Pairs) :-
%     dict_pairs(Symtab, symtab,  Pairs).


