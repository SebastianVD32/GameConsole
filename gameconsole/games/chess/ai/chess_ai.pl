/*  chess_ai.pl — Motor de decisión de ajedrez para GameConsole.

    Entrada:  la posición en notación FEN (la envía Python).
    Salida:   el mejor movimiento encontrado (p. ej. "e2e4" o "e7e8q"),
              su evaluación en centipeones y la cantidad de nodos visitados.

    Algoritmo:
      1. Generación de movimientos legales propia (incluye enroque, captura al
         paso y promoción), verificando que el rey propio no quede en jaque.
      2. Búsqueda negamax con poda alfa-beta a profundidad fija.
      3. Búsqueda de quiescencia sobre capturas para evitar el "efecto
         horizonte" (no detenerse en mitad de un intercambio).
      4. Ordenamiento de movimientos MVV-LVA (víctima más valiosa, atacante
         menos valioso) para que la poda alfa-beta sea eficaz.
      5. Evaluación estática: material + tablas de posición por pieza.

    Representación:
      st(Board, Side, Castle, EP)
        Board  = término b/64; la casilla I (0 = a1, 63 = h8) es arg(I+1).
                 Cada casilla es e (vacía) o pc(Color, Tipo).
        Side   = w | b
        Castle = c(WK, WQ, BK, BQ) con valores 0/1
        EP     = índice de la casilla de captura al paso o -1
      Movimiento: m(Desde, Hasta, Promocion), Promocion = none | q | r | b | n
*/

:- module(chess_ai,
          [ best_move/5,          % +FEN, +Depth, -Move, -Score, -Nodes
            legal_move_list/2,    % +FEN, -Moves
            perft/3,              % +FEN, +Depth, -Count
            evaluate_fen/2        % +FEN, -Score
          ]).

:- use_module(library(lists)).
:- use_module(library(apply)).
:- use_module(library(pairs)).
:- use_module(library(random)).

mate_score(100000).
infinity(1000000).
max_quiescence_depth(6).

% ---------------------------------------------------------------- interfaz

best_move(FEN, Depth, MoveText, Score, Nodes) :-
    must_be(positive_integer, Depth),
    fen_state(FEN, State),
    nb_setval(chess_ai_nodes, 0),
    findall(M-S, legal_move(State, M, S), Children0),
    Children0 \== [],
    random_permutation(Children0, Shuffled),     % variedad entre jugadas equivalentes
    order_children(State, Shuffled, Children),
    infinity(Inf), Alpha is -Inf,
    D1 is Depth - 1,
    root_search(Children, D1, Alpha, Inf, none, BestMove, Score),
    nb_getval(chess_ai_nodes, Nodes),
    move_text(BestMove, MoveText).

legal_move_list(FEN, Moves) :-
    fen_state(FEN, State),
    findall(T, (legal_move(State, M, _), move_text(M, T)), Moves0),
    msort(Moves0, Moves).

perft(FEN, Depth, Count) :-
    fen_state(FEN, State),
    perft_state(State, Depth, Count).

evaluate_fen(FEN, Score) :-
    fen_state(FEN, State),
    evaluate(State, Score).

perft_state(_, 0, 1) :- !.
perft_state(State, Depth, Count) :-
    D1 is Depth - 1,
    findall(N, (legal_move(State, _, Next), perft_state(Next, D1, N)), Ns),
    sum_list(Ns, Count).

% ---------------------------------------------------------------- búsqueda

root_search([], _, Alpha, _, Best, Best, Alpha).
root_search([Move-Next|Rest], Depth, Alpha, Beta, Best0, Best, Score) :-
    NA is -Beta, NB is -Alpha,
    negamax(Next, Depth, 1, NA, NB, S0),
    S is -S0,
    (   ( S > Alpha ; Best0 == none )
    ->  root_search(Rest, Depth, S, Beta, Move, Best, Score)
    ;   root_search(Rest, Depth, Alpha, Beta, Best0, Best, Score)
    ).

%  negamax(+State, +Depth, +Ply, +Alpha, +Beta, -Score)
%  Puntaje desde el punto de vista del bando que mueve en State (fail-hard).
negamax(State, Depth, Ply, Alpha, Beta, Score) :-
    count_node,
    (   Depth =< 0
    ->  quiesce(State, Alpha, Beta, 0, Score)
    ;   findall(M-S, legal_move(State, M, S), Children0),
        (   Children0 == []
        ->  terminal_score(State, Ply, Score)
        ;   order_children(State, Children0, Children),
            D1 is Depth - 1, P1 is Ply + 1,
            alphabeta(Children, D1, P1, Alpha, Beta, Score)
        )
    ).

alphabeta([], _, _, Alpha, _, Alpha).
alphabeta([_-Next|Rest], Depth, Ply, Alpha, Beta, Score) :-
    NA is -Beta, NB is -Alpha,
    negamax(Next, Depth, Ply, NA, NB, S0),
    S is -S0,
    (   S >= Beta
    ->  Score = Beta                                  % poda beta
    ;   Alpha1 is max(Alpha, S),
        alphabeta(Rest, Depth, Ply, Alpha1, Beta, Score)
    ).

%  Sin movimientos legales: jaque mate (peor cuanto antes) o ahogado (tablas).
terminal_score(st(Board, Side, _, _), Ply, Score) :-
    (   in_check(Board, Side)
    ->  mate_score(Mate), Score is -(Mate - Ply)
    ;   Score = 0
    ).

%  Quiescencia: solo capturas y promociones hasta que la posición esté "quieta".
quiesce(State, Alpha, Beta, QDepth, Score) :-
    evaluate(State, StandPat),
    (   StandPat >= Beta
    ->  Score = Beta
    ;   Alpha1 is max(Alpha, StandPat),
        max_quiescence_depth(MaxQ),
        (   QDepth >= MaxQ
        ->  Score = Alpha1
        ;   findall(M-S, tactical_move(State, M, S), Children0),
            order_children(State, Children0, Children),
            Q1 is QDepth + 1,
            quiesce_loop(Children, Q1, Alpha1, Beta, Score)
        )
    ).

quiesce_loop([], _, Alpha, _, Alpha).
quiesce_loop([_-Next|Rest], QDepth, Alpha, Beta, Score) :-
    count_node,
    NA is -Beta, NB is -Alpha,
    quiesce(Next, NA, NB, QDepth, S0),
    S is -S0,
    (   S >= Beta
    ->  Score = Beta
    ;   Alpha1 is max(Alpha, S),
        quiesce_loop(Rest, QDepth, Alpha1, Beta, Score)
    ).

count_node :-
    nb_getval(chess_ai_nodes, N0),
    N is N0 + 1,
    nb_setval(chess_ai_nodes, N).

%  Ordenamiento MVV-LVA: capturas valiosas con atacantes baratos primero.
order_children(st(Board, _, _, _), Children, Ordered) :-
    map_list_to_pairs(move_priority(Board), Children, Keyed),
    keysort(Keyed, Sorted),
    pairs_values(Sorted, Ordered).

move_priority(Board, m(F, T, P)-_, Key) :-
    cell(Board, F, pc(_, Attacker)),
    cell(Board, T, Target),
    (   Target = pc(_, Victim)
    ->  piece_value(Victim, VV), piece_value(Attacker, AV),
        Gain is 10 * VV - AV
    ;   Gain = 0
    ),
    (   P == none -> Promo = 0 ; piece_value(P, Promo) ),
    Key is -(Gain + Promo).

% ---------------------------------------------------------------- evaluación

%  Evaluación desde el punto de vista del bando que mueve.
evaluate(st(Board, Side, _, _), Score) :-
    Board =.. [b|Cells],
    foldl(score_cell, Cells, 0-0, _-White),
    (   Side == w -> Score = White ; Score is -White ).

score_cell(e, I0-S, I-S) :- !, I is I0 + 1.
score_cell(pc(Color, Type), I0-S0, I-S) :-
    I is I0 + 1,
    piece_value(Type, Value),
    (   Color == w -> Index = I0 ; Index is I0 xor 56 ),   % espejo vertical para negras
    pst(Type, Table), Arg is Index + 1, arg(Arg, Table, Bonus),
    (   Color == w -> S is S0 + Value + Bonus ; S is S0 - Value - Bonus ).

piece_value(p, 100).
piece_value(n, 320).
piece_value(b, 330).
piece_value(r, 500).
piece_value(q, 900).
piece_value(k, 0).

%  Tablas de posición desde el punto de vista de las blancas, a1..h8.
%  Premian el centro, el desarrollo de piezas menores, el avance de peones
%  y un rey resguardado tras el enroque.
pst(p, t(  0,  0,  0,  0,  0,  0,  0,  0,
           5, 10, 10,-20,-20, 10, 10,  5,
           5, -5,-10,  0,  0,-10, -5,  5,
           0,  0,  0, 20, 20,  0,  0,  0,
           5,  5, 10, 25, 25, 10,  5,  5,
          10, 10, 20, 30, 30, 20, 10, 10,
          50, 50, 50, 50, 50, 50, 50, 50,
           0,  0,  0,  0,  0,  0,  0,  0)).
pst(n, t(-50,-40,-30,-30,-30,-30,-40,-50,
         -40,-20,  0,  5,  5,  0,-20,-40,
         -30,  5, 10, 15, 15, 10,  5,-30,
         -30,  0, 15, 20, 20, 15,  0,-30,
         -30,  5, 15, 20, 20, 15,  5,-30,
         -30,  0, 10, 15, 15, 10,  0,-30,
         -40,-20,  0,  0,  0,  0,-20,-40,
         -50,-40,-30,-30,-30,-30,-40,-50)).
pst(b, t(-20,-10,-10,-10,-10,-10,-10,-20,
         -10,  5,  0,  0,  0,  0,  5,-10,
         -10, 10, 10, 10, 10, 10, 10,-10,
         -10,  0, 10, 10, 10, 10,  0,-10,
         -10,  5,  5, 10, 10,  5,  5,-10,
         -10,  0,  5, 10, 10,  5,  0,-10,
         -10,  0,  0,  0,  0,  0,  0,-10,
         -20,-10,-10,-10,-10,-10,-10,-20)).
pst(r, t(  0,  0,  0,  5,  5,  0,  0,  0,
          -5,  0,  0,  0,  0,  0,  0, -5,
          -5,  0,  0,  0,  0,  0,  0, -5,
          -5,  0,  0,  0,  0,  0,  0, -5,
          -5,  0,  0,  0,  0,  0,  0, -5,
          -5,  0,  0,  0,  0,  0,  0, -5,
           5, 10, 10, 10, 10, 10, 10,  5,
           0,  0,  0,  0,  0,  0,  0,  0)).
pst(q, t(-20,-10,-10, -5, -5,-10,-10,-20,
         -10,  0,  5,  0,  0,  0,  0,-10,
         -10,  5,  5,  5,  5,  5,  0,-10,
           0,  0,  5,  5,  5,  5,  0, -5,
          -5,  0,  5,  5,  5,  5,  0, -5,
         -10,  0,  5,  5,  5,  5,  0,-10,
         -10,  0,  0,  0,  0,  0,  0,-10,
         -20,-10,-10, -5, -5,-10,-10,-20)).
pst(k, t( 20, 30, 10,  0,  0, 10, 30, 20,
          20, 20,  0,  0,  0,  0, 20, 20,
         -10,-20,-20,-20,-20,-20,-20,-10,
         -20,-30,-30,-40,-40,-30,-30,-20,
         -30,-40,-40,-50,-50,-40,-40,-30,
         -30,-40,-40,-50,-50,-40,-40,-30,
         -30,-40,-40,-50,-50,-40,-40,-30,
         -30,-40,-40,-50,-50,-40,-40,-30)).

% ---------------------------------------------------------------- reglas

cell(Board, I, Cell) :- A is I + 1, arg(A, Board, Cell).

opponent(w, b).
opponent(b, w).

forward(w, 1).
forward(b, -1).

%  offset(+Desde, +DF, +DR, -Hasta): desplazamiento dentro del tablero.
offset(I, DF, DR, T) :-
    F is I mod 8 + DF, R is I // 8 + DR,
    F >= 0, F < 8, R >= 0, R < 8,
    T is R * 8 + F.

knight_step(1, 2).  knight_step(2, 1).  knight_step(2, -1). knight_step(1, -2).
knight_step(-1, -2). knight_step(-2, -1). knight_step(-2, 1). knight_step(-1, 2).

king_step(DF, DR) :- member(DF, [-1, 0, 1]), member(DR, [-1, 0, 1]), \+ (DF == 0, DR == 0).

rook_dir(1, 0). rook_dir(-1, 0). rook_dir(0, 1). rook_dir(0, -1).
bishop_dir(1, 1). bishop_dir(1, -1). bishop_dir(-1, 1). bishop_dir(-1, -1).

piece_dir(r, DF, DR) :- rook_dir(DF, DR).
piece_dir(b, DF, DR) :- bishop_dir(DF, DR).
piece_dir(q, DF, DR) :- rook_dir(DF, DR) ; bishop_dir(DF, DR).

%  legal_move(+State, -Move, -NextState)
legal_move(State, Move, Next) :-
    State = st(_, Side, _, _),
    pseudo_move(State, Move),
    make_move(State, Move, Next),
    Next = st(Board2, _, _, _),
    \+ in_check(Board2, Side).

%  Capturas y promociones legales (para la quiescencia).
tactical_move(State, Move, Next) :-
    State = st(Board, Side, _, EP),
    pseudo_move(State, Move),
    Move = m(F, T, P),
    (   cell(Board, T, pc(_, _)) -> true
    ;   P \== none -> true
    ;   T =:= EP, cell(Board, F, pc(_, p))
    ),
    make_move(State, Move, Next),
    Next = st(Board2, _, _, _),
    \+ in_check(Board2, Side).

pseudo_move(st(Board, Side, Castle, EP), Move) :-
    between(0, 63, F),
    cell(Board, F, pc(Side, Type)),
    piece_move(Type, Board, Side, Castle, EP, F, Move).

piece_move(n, Board, Side, _, _, F, m(F, T, none)) :-
    knight_step(DF, DR), offset(F, DF, DR, T), free_or_enemy(Board, Side, T).
piece_move(k, Board, Side, _, _, F, m(F, T, none)) :-
    king_step(DF, DR), offset(F, DF, DR, T), free_or_enemy(Board, Side, T).
piece_move(k, Board, Side, Castle, _, F, Move) :-
    castling_move(Board, Side, Castle, F, Move).
piece_move(Type, Board, Side, _, _, F, m(F, T, none)) :-
    memberchk(Type, [r, b, q]),
    piece_dir(Type, DF, DR),
    slide(Board, Side, F, DF, DR, T).
piece_move(p, Board, Side, _, EP, F, Move) :-
    pawn_move(Board, Side, EP, F, Move).

free_or_enemy(Board, Side, T) :-
    cell(Board, T, Cell),
    (   Cell == e -> true ; Cell = pc(Other, _), Other \== Side ).

slide(Board, Side, F, DF, DR, T) :-
    offset(F, DF, DR, Next),
    cell(Board, Next, Cell),
    (   Cell == e
    ->  ( T = Next ; slide(Board, Side, Next, DF, DR, T) )
    ;   Cell = pc(Other, _), Other \== Side, T = Next
    ).

pawn_move(Board, Side, _, F, Move) :-              % avance simple y doble
    forward(Side, Dir),
    offset(F, 0, Dir, T1), cell(Board, T1, e),
    (   promotion_moves(Side, F, T1, Move)
    ;   start_rank(Side, Rank), F // 8 =:= Rank,
        offset(F, 0, 2 * Dir, T2), cell(Board, T2, e),
        Move = m(F, T2, none)
    ).
pawn_move(Board, Side, EP, F, Move) :-             % capturas y al paso
    forward(Side, Dir),
    member(DF, [-1, 1]),
    offset(F, DF, Dir, T),
    cell(Board, T, Cell),
    (   Cell = pc(Other, _), Other \== Side
    ->  promotion_moves(Side, F, T, Move)
    ;   Cell == e, T =:= EP, Move = m(F, T, none)
    ).

promotion_moves(Side, F, T, Move) :-
    last_rank(Side, Last),
    (   T // 8 =:= Last
    ->  member(P, [q, r, b, n]), Move = m(F, T, P)
    ;   Move = m(F, T, none)
    ).

start_rank(w, 1).
start_rank(b, 6).
last_rank(w, 7).
last_rank(b, 0).

castling_move(Board, w, c(1, _, _, _), 4, m(4, 6, none)) :-
    cell(Board, 7, pc(w, r)), cell(Board, 5, e), cell(Board, 6, e),
    \+ attacked(Board, 4, b), \+ attacked(Board, 5, b), \+ attacked(Board, 6, b).
castling_move(Board, w, c(_, 1, _, _), 4, m(4, 2, none)) :-
    cell(Board, 0, pc(w, r)), cell(Board, 1, e), cell(Board, 2, e), cell(Board, 3, e),
    \+ attacked(Board, 4, b), \+ attacked(Board, 3, b), \+ attacked(Board, 2, b).
castling_move(Board, b, c(_, _, 1, _), 60, m(60, 62, none)) :-
    cell(Board, 63, pc(b, r)), cell(Board, 61, e), cell(Board, 62, e),
    \+ attacked(Board, 60, w), \+ attacked(Board, 61, w), \+ attacked(Board, 62, w).
castling_move(Board, b, c(_, _, _, 1), 60, m(60, 58, none)) :-
    cell(Board, 56, pc(b, r)), cell(Board, 57, e), cell(Board, 58, e), cell(Board, 59, e),
    \+ attacked(Board, 60, w), \+ attacked(Board, 59, w), \+ attacked(Board, 58, w).

%  attacked(+Board, +Square, +ByColor)
attacked(Board, Sq, By) :-
    knight_step(DF, DR), offset(Sq, DF, DR, T), cell(Board, T, pc(By, n)), !.
attacked(Board, Sq, By) :-
    king_step(DF, DR), offset(Sq, DF, DR, T), cell(Board, T, pc(By, k)), !.
attacked(Board, Sq, By) :-
    forward(By, Dir), Back is -Dir,
    member(DF, [-1, 1]), offset(Sq, DF, Back, T), cell(Board, T, pc(By, p)), !.
attacked(Board, Sq, By) :-
    rook_dir(DF, DR), first_piece(Board, Sq, DF, DR, pc(By, Type)),
    memberchk(Type, [r, q]), !.
attacked(Board, Sq, By) :-
    bishop_dir(DF, DR), first_piece(Board, Sq, DF, DR, pc(By, Type)),
    memberchk(Type, [b, q]), !.

first_piece(Board, Sq, DF, DR, Piece) :-
    offset(Sq, DF, DR, Next),
    cell(Board, Next, Cell),
    (   Cell == e -> first_piece(Board, Next, DF, DR, Piece) ; Piece = Cell ).

in_check(Board, Side) :-
    king_square(Board, Side, K),
    opponent(Side, Enemy),
    attacked(Board, K, Enemy).

king_square(Board, Side, K) :-
    between(0, 63, K), cell(Board, K, pc(Side, k)), !.

%  make_move(+State, +Move, -NextState)
make_move(st(Board, Side, Castle, EP), m(F, T, P), st(Board2, Enemy, Castle2, EP2)) :-
    opponent(Side, Enemy),
    cell(Board, F, pc(Side, Type)),
    (   P == none -> Placed = pc(Side, Type) ; Placed = pc(Side, P) ),
    Changes0 = [F-e, T-Placed],
    (   Type == k, abs(T - F) =:= 2
    ->  (   T > F
        ->  RF is F + 3, RT is F + 1
        ;   RF is F - 4, RT is F - 1
        ),
        Changes = [RF-e, RT-pc(Side, r)|Changes0]
    ;   Type == p, T =:= EP, F mod 8 =\= T mod 8
    ->  forward(Side, Dir), Captured is T - 8 * Dir,
        Changes = [Captured-e|Changes0]
    ;   Changes = Changes0
    ),
    Board =.. [b|Cells0],
    apply_changes(Cells0, 0, Changes, Cells),
    Board2 =.. [b|Cells],
    (   Type == p, abs(T - F) =:= 16 -> EP2 is (F + T) // 2 ; EP2 = -1 ),
    update_castle(Castle, F, T, Castle2).

apply_changes([], _, _, []).
apply_changes([C0|Cs0], I, Changes, [C|Cs]) :-
    (   memberchk(I-New, Changes) -> C = New ; C = C0 ),
    I1 is I + 1,
    apply_changes(Cs0, I1, Changes, Cs).

update_castle(c(WK0, WQ0, BK0, BQ0), F, T, c(WK, WQ, BK, BQ)) :-
    lose_right(WK0, [4, 7], F, T, WK),
    lose_right(WQ0, [4, 0], F, T, WQ),
    lose_right(BK0, [60, 63], F, T, BK),
    lose_right(BQ0, [60, 56], F, T, BQ).

lose_right(R0, Squares, F, T, R) :-
    (   ( memberchk(F, Squares) ; memberchk(T, Squares) ) -> R = 0 ; R = R0 ).

% ---------------------------------------------------------------- FEN

fen_state(FEN, st(Board, Side, Castle, EP)) :-
    split_string(FEN, " ", " ", [Placement, SideS, CastleS, EPS|_]),
    split_string(Placement, "/", "", Rows),
    length(Rows, 8),
    maplist(expand_row, Rows, Expanded),
    reverse(Expanded, FromRank1),
    append(FromRank1, Cells),
    length(Cells, 64),
    Board =.. [b|Cells],
    atom_string(Side, SideS),
    memberchk(Side, [w, b]),
    castle_flags(CastleS, Castle),
    (   EPS == "-" -> EP = -1 ; square_index(EPS, EP) ).

expand_row(Row, Cells) :-
    string_chars(Row, Chars),
    foldl(expand_char, Chars, Cells, []),
    length(Cells, 8).

expand_char(Char, Cells, Tail) :-
    (   char_type(Char, digit(N))
    ->  length(Empty, N), maplist(=(e), Empty), append(Empty, Tail, Cells)
    ;   fen_piece(Char, Piece), Cells = [Piece|Tail]
    ).

fen_piece(Char, pc(Color, Type)) :-
    downcase_atom(Char, Type),
    (   Type == Char -> Color = b ; Color = w ),
    memberchk(Type, [p, n, b, r, q, k]).

castle_flags(S, c(WK, WQ, BK, BQ)) :-
    flag_in("K", S, WK), flag_in("Q", S, WQ), flag_in("k", S, BK), flag_in("q", S, BQ).

flag_in(F, S, 1) :- sub_string(S, _, _, _, F), !.
flag_in(_, _, 0).

square_index(Text, I) :-
    string_chars(Text, [FC, RC]),
    char_code(FC, FCode), char_code(RC, RCode),
    F is FCode - 0'a, R is RCode - 0'1,
    F >= 0, F < 8, R >= 0, R < 8,
    I is R * 8 + F.

square_text(I, Text) :-
    F is I mod 8, R is I // 8,
    FCode is 0'a + F, RCode is 0'1 + R,
    string_codes(Text, [FCode, RCode]).

move_text(m(F, T, P), Text) :-
    square_text(F, FT), square_text(T, TT),
    (   P == none -> PT = "" ; atom_string(P, PT) ),
    atomics_to_string([FT, TT, PT], Text).
