import numpy as np
import terminator.CDT.DT.tools.BRIO_2D_multidimarr as BRIO
from terminator.CDT.DT.tools.adaptive_predicates import incircle, orient2d, exactinit2d
# import BTP.experimental.pass_garray_to_predicates.tools.BRIO_2D_multidimarr as BRIO
# from BTP.experimental.pass_garray_to_predicates.tools.adaptive_predicates import incircle, orient2d, exactinit2d
import time


def njit(f=None, cache=None):
    if cache == None:
        return f
    else:
        def wrap(f):
            return f
        return wrap
# from numba import njit


@njit(cache=True)
def _walk(
        point_id, t_index, vertices_ID, neighbour_ID, points, gv, res_arr,
        global_arr):
    '''
    Walks from the given tri (t_index) to the tri enclosing the given point.

        point_id : The index (corresponding to the points array) of the
                   point to be inserted into the triangulation.
         t_index : The index of the tri to start the walk from.
     vertices_ID : The global array storing all the indices (corresponding
                   to the points array) of the vertices of all the tri.
    neighbour_ID : The global array storing the indices of the neighbouring
                   tri.
          points : The global array storing the co-ordinates of all the
                   points to be triangulated.
              gv : Index assigned to the ghost vertex.
    '''

    gv_idx = 3
    if vertices_ID[t_index, 1] == gv:
        gv_idx = 1
    elif vertices_ID[t_index, 2] == gv:
        gv_idx = 2

    if gv_idx != 3:
        # t_index is a ghost tri, in this case simply step into the adjacent
        # real triangle.
        t_index = neighbour_ID[t_index, gv_idx]//3

    point_x = points[point_id, 0]
    point_y = points[point_id, 1]

    while True:
        # i.e. t_index is a real tri

        t_op_index_in_t = 4

        a_x = points[vertices_ID[t_index, 0], 0]
        a_y = points[vertices_ID[t_index, 0], 1]
        b_x = points[vertices_ID[t_index, 1], 0]
        b_y = points[vertices_ID[t_index, 1], 1]
        c_x = points[vertices_ID[t_index, 2], 0]
        c_y = points[vertices_ID[t_index, 2], 1]

        
        det = orient2d(
            point_x, point_y, c_x, c_y, b_x, b_y, res_arr, global_arr)
        if det > 0:
            t_op_index_in_t = 0
        else:
            det = orient2d(
                point_x, point_y, a_x, a_y, c_x, c_y, res_arr, global_arr)
            if det > 0:
                t_op_index_in_t = 1
            else:
                det = orient2d(
                    point_x, point_y, b_x, b_y, a_x, a_y, res_arr, global_arr)
                if det > 0:
                    t_op_index_in_t = 2

        if t_op_index_in_t != 4:
            t_index = neighbour_ID[t_index, t_op_index_in_t]//3
        else:
            # point_id lies inside t_index
            break

        if vertices_ID[t_index, 1] == gv:
            break
        elif vertices_ID[t_index, 2] == gv:
            break

    return t_index


@njit(cache=True)
def _cavity_helper(
        point_id, t_index, points, vertices_ID, gv, res_arr, global_arr):
    '''
    Checks whether the given point lies inside the circumsphere the given tri.
    Returns True if it does.

            point_id : The index (corresponding to the points array) of the
                       point to be inserted into the triangulation.
             t_index : The index of the tri to check.
              points : The global array storing the co-ordinates of all the
                       points to be triangulated.
         vertices_ID : The global array storing all the indices (corresponding
                       to the points array) of the vertices of all the tri.
    sub_determinants : The global array storing the sub-determinants of all the
                       tri.
                  gv : Index assigned to the ghost vertex.
    '''

    gv_idx = 3
    if vertices_ID[t_index, 1] == gv:
        gv_idx = 1
    elif vertices_ID[t_index, 2] == gv:
        gv_idx = 2

    p_x = points[point_id, 0]
    p_y = points[point_id, 1]

    if gv_idx != 3:
        # t_index is a ghost triangle
        b_x = points[vertices_ID[t_index, (gv_idx + 1) % 3], 0]
        b_y = points[vertices_ID[t_index, (gv_idx + 1) % 3], 1]
        c_x = points[vertices_ID[t_index, (gv_idx + 2) % 3], 0]
        c_y = points[vertices_ID[t_index, (gv_idx + 2) % 3], 1]

        det = orient2d(p_x, p_y, b_x, b_y, c_x, c_y, res_arr, global_arr)

        if det > 0:
            return True
        elif det == 0:
            m1_x = p_x - b_x
            m2_x = c_x - p_x
            m1_y = p_y - b_y
            m2_y = c_y - p_y
            if m1_x*m2_x >= 0 and m1_y*m2_y >= 0:
                return True
            else:
                return False
        else:
            return False
    else:
        # t_index is a real triangle
        a_x = points[vertices_ID[t_index, 0], 0]
        a_y = points[vertices_ID[t_index, 0], 1]
        b_x = points[vertices_ID[t_index, 1], 0]
        b_y = points[vertices_ID[t_index, 1], 1]
        c_x = points[vertices_ID[t_index, 2], 0]
        c_y = points[vertices_ID[t_index, 2], 1]

        det = incircle(
            a_x, a_y, b_x, b_y, c_x, c_y, p_x, p_y, res_arr, global_arr)

        if det >= 0.0:
            return True
        else:
            return False


@njit(cache=True)
def _identify_cavity(
        points, point_id, t_index, neighbour_ID, vertices_ID, ic_bad_tri,
        ic_boundary_tri, ic_boundary_vtx, gv, bad_tri_indicator_arr, res_arr,
        global_arr):
    '''
    Identifies all the 'bad' triangles, i.e. the triangles whose circumcircles
    enclose the given point. Returns a list of the indices of the bad triangles
    and a list of the triangles bordering the cavity.

              points : The global array containing the co-ordinates of all the
                       points to be triangulated.
            point_id : The index (corresponding to the points array) of the
                       point to be inserted into the triangulation.
             t_index : The index of the tri enclosing point_id.
        neighbour_ID : The global array containing the indices of the
                       neighbours of all the triangles.
         vertices_ID : The global array containing the indices (corresponding
                       to the points array) of the vertices of all the tri.
          ic_bad_tri : Helper array, used to store the indices of the 'bad'
                       tri, i.e. those whose circumspheres containt point_id.
     ic_boundary_tri : Helper array, used to store the tri on the boundary of
                       the cavity.
     ic_boundary_vtx : Helper array, used to store the points on the boundary
                       of the cavity.
                  gv : Index assigned to the ghost vertex.
    '''

    ic_len_bad_tri = len(ic_bad_tri)
    ic_bad_tri_end = np.int64(0)

    ic_len_boundary_tri = len(ic_boundary_tri)
    ic_boundary_tri_end = np.int64(0)

    ic_len_boundary_vtx = len(ic_boundary_vtx)
    ic_boundary_vtx_end = np.int64(0)

    # Adding the first bad triangle, i.e. the enclosing triangle
    ic_bad_tri[ic_bad_tri_end] = t_index
    bad_tri_indicator_arr[t_index] = True
    ic_bad_tri_end += 1

    ic_idx = 0
    while True:
        t_index = ic_bad_tri[ic_idx]

        for j in range(3):
            jth_nbr_idx = neighbour_ID[t_index, j]//3

            if not bad_tri_indicator_arr[jth_nbr_idx]:
                # i.e. jth_nbr_idx has not been stored in the ic_bad_tri
                # array yet.
                inside_tri = _cavity_helper(
                    point_id, jth_nbr_idx, points, vertices_ID, gv, res_arr,
                    global_arr)
                if inside_tri is True:
                    # i.e. the j'th neighbour is a bad triangle
                    if ic_bad_tri_end >= ic_len_bad_tri:
                        temp_arr1 = np.empty(2*ic_len_bad_tri, dtype=np.int64)
                        for l in range(ic_bad_tri_end):
                            temp_arr1[l] = ic_bad_tri[l]
                        ic_len_bad_tri = 2*ic_len_bad_tri
                        ic_bad_tri = temp_arr1

                    ic_bad_tri[ic_bad_tri_end] = jth_nbr_idx
                    ic_bad_tri_end += 1
                    bad_tri_indicator_arr[jth_nbr_idx] = True
                else:
                    # i.e. the j'th neighbour is a boundary triangle
                    if ic_boundary_tri_end >= ic_len_boundary_tri:
                        temp_arr2 = np.empty(
                            2*ic_len_boundary_tri,
                            dtype=np.int64
                        )
                        for l in range(ic_boundary_tri_end):
                            temp_arr2[l] = ic_boundary_tri[l]
                        ic_len_boundary_tri = 2*ic_len_boundary_tri
                        ic_boundary_tri = temp_arr2

                    ic_boundary_tri[ic_boundary_tri_end] = neighbour_ID[
                        t_index, j]
                    ic_boundary_tri_end += 1

                    # Storing the vertices of t_index that lie on the boundary
                    if ic_boundary_vtx_end >= ic_len_boundary_vtx:
                        temp_arr3 = np.empty(
                            shape=(2*ic_len_boundary_vtx, 2),
                            dtype=np.int64
                        )
                        for l in range(ic_boundary_vtx_end):
                            temp_arr3[l, 0] = ic_boundary_vtx[l, 0]
                            temp_arr3[l, 1] = ic_boundary_vtx[l, 1]
                        ic_len_boundary_vtx = 2*ic_len_boundary_vtx
                        ic_boundary_vtx = temp_arr3

                    ic_boundary_vtx[ic_boundary_vtx_end, 0] = vertices_ID[
                        t_index, (j+1) % 3]
                    ic_boundary_vtx[ic_boundary_vtx_end, 1] = vertices_ID[
                        t_index, (j+2) % 3]

                    ic_boundary_vtx_end += 1

        ic_idx += 1

        if ic_idx == ic_bad_tri_end:
            break

    return ic_bad_tri, ic_bad_tri_end, ic_boundary_tri, \
           ic_boundary_tri_end, ic_boundary_vtx


@njit(cache=True)
def _make_Delaunay_ball(
        point_id, bad_tri, bad_tri_end, boundary_tri, boundary_tri_end,
        boundary_vtx, points, neighbour_ID, vertices_ID, num_tri, gv):
    '''
    Joins all the vertices on the boundary to the new point, and forms
    the corresponding triangles along with their adjacencies. Returns the index
    of a new triangle, to be used as the starting point of the next walk.

         point_id : The index corresponding to the points array of the point to
                    be inserted into the triangulation.
         bad_tri : The list of tri whose circumcircle contains point_id.
    boundary_tri : The list of triangles lying on the boundary of the cavity
                    formed by the bad triangles.
     boundary_vtx : The vertices lying on the boundary of the cavity formed by
                    all the bad triangles.
           points : The global array storing the co-ordinates of all the points
                    to be triangulated.
    '''

    # populating the cavity with new triangles
    for i in range(boundary_tri_end):
        if i < bad_tri_end:
            t_index = bad_tri[i]
        else:
            t_index = num_tri
            num_tri += 1

        t_info = boundary_tri[i]
        neighbour_ID[t_index, 0] = t_info
        vertices_ID[t_index, 0] = point_id
        vertices_ID[t_index, 1] = boundary_vtx[i, 0]
        vertices_ID[t_index, 2] = boundary_vtx[i, 1]
        neighbour_ID[t_info//3, t_info % 3] = 3*t_index

    for i in range(boundary_tri_end):
        if i < bad_tri_end:
            t1 = bad_tri[i]
        else:
            t1 = num_tri - (boundary_tri_end - i)
        for j in range(boundary_tri_end):
            if j < bad_tri_end:
                t2 = bad_tri[j]
            else:
                t2 = num_tri - (boundary_tri_end - j)
            if vertices_ID[t1, 1] == vertices_ID[t2, 2]:
                neighbour_ID[t1, 2] = 3*t2+1
                neighbour_ID[t2, 1] = 3*t1+2
                break

    old_tri =  bad_tri[bad_tri_end-1]

    if boundary_tri_end < bad_tri_end:
        print("oops")
        # print("boundary_tri_end : {}".format(boundary_tri_end))
        # print("bad_tri_end : {}".format(bad_tri_end))
        old_tri = bad_tri[boundary_tri_end-1]
        for k in range(boundary_tri_end, bad_tri_end):
            tri = bad_tri[k]
            for t in range(tri, num_tri):
                vertices_ID[t, 0] = vertices_ID[t+1, 0]
                vertices_ID[t, 1] = vertices_ID[t+1, 1]
                vertices_ID[t, 2] = vertices_ID[t+1, 2]

                neighbour_ID[t, 0] = neighbour_ID[t+1, 0]
                neighbour_ID[t, 1] = neighbour_ID[t+1, 1]
                neighbour_ID[t, 2] = neighbour_ID[t+1, 2]

            num_tri -= 1

            for i in range(num_tri):
                for j in range(3):
                    if neighbour_ID[i, j]//3 > tri:
                        neighbour_ID[i, j] = 3*(neighbour_ID[i, j]//3-1) + \
                                              neighbour_ID[i, j] % 3

            for i in range(k+1, bad_tri_end):
                if bad_tri[i] > tri:
                    bad_tri[i] -= 1

    return num_tri, old_tri


@njit(cache=True)
def assembly(
        points, vertices_ID, neighbour_ID, insertion_seq, gv, ic_bad_tri,
        ic_boundary_tri, ic_boundary_vtx, bad_tri_indicator_arr, global_arr,
        res_arr):

    exactinit2d(points, res_arr)
    num_tri = initialize(points, vertices_ID, neighbour_ID, insertion_seq, gv)
    old_tri = np.int64(0)

    for point_id in range(3, gv):
        enclosing_tri = _walk(
            point_id, old_tri, vertices_ID, neighbour_ID, points, gv, res_arr,
            global_arr)

        ic_bad_tri, ic_bad_tri_end, ic_boundary_tri, ic_boundary_tri_end, \
        ic_boundary_vtx = _identify_cavity(
            points, point_id, enclosing_tri, neighbour_ID, vertices_ID,
            ic_bad_tri, ic_boundary_tri, ic_boundary_vtx, gv,
            bad_tri_indicator_arr, res_arr, global_arr)

        num_tri, old_tri = _make_Delaunay_ball(
            point_id, ic_bad_tri, ic_bad_tri_end, ic_boundary_tri,
            ic_boundary_tri_end, ic_boundary_vtx, points, neighbour_ID,
            vertices_ID, num_tri, gv)

        for i in range(ic_bad_tri_end):
            t = ic_bad_tri[i]
            bad_tri_indicator_arr[t] = False

    return


@njit(cache=True)
def exportDT_njit(
        vertices_ID, neighbour_ID, insertion_seq, num_tri, ghost_tri,
        rectified_vertices, rectified_nbrs, gv):

    gt_end = 0
    rt_end = 0
    for i in range(num_tri):
        is_gt = False
        # The first vertex of a triangle can never be a ghost vertex, since in
        # every newly created traingle the first vertex is set to the point
        # being inserted.
        if vertices_ID[i, 1] == gv:
            is_gt = True
        elif vertices_ID[i, 2] == gv:
            is_gt = True

        if is_gt == True:
            ghost_tri[gt_end] = i
            gt_end += 1
        else:
            for j in range(3):
                rectified_vertices[rt_end, j] = insertion_seq[
                    vertices_ID[i, j]]
                rectified_nbrs[rt_end, j] = neighbour_ID[i, j]//3
            rt_end += 1

    for i in range(gt_end-1, -1, -1):
        tri = ghost_tri[i]
        for j in range(rt_end):
            for k in range(3):
                nbr = rectified_nbrs[j, k]
                if nbr > tri:
                    rectified_nbrs[j, k] = nbr - 1
                elif nbr == tri:
                    rectified_nbrs[j, k] = -1

    return rt_end


@njit(cache=True)
def initialize(points, vertices_ID, neighbour_ID, insertion_seq, gv):

    a_x = points[0, 0]
    a_y = points[0, 1]
    b_x = points[1, 0]
    b_y = points[1, 1]

    num_tri = np.int64(0)

    idx = 2
    while idx < gv:
        p_x = points[idx, 0]
        p_y = points[idx, 1]
        signed_area = (b_x-a_x)*(p_y-a_y)-(p_x-a_x)*(b_y-a_y)
        if signed_area > 0:
            points[2, 0], points[idx, 0] = points[idx, 0], points[2, 0]
            points[2, 1], points[idx, 1] = points[idx, 1], points[2, 1]
            insertion_seq[2], insertion_seq[idx] = insertion_seq[idx], \
            insertion_seq[2]
            break
        elif signed_area < 0:
            points[2, 0], points[idx, 0] = points[idx, 0], points[2, 0]
            points[2, 1], points[idx, 1] = points[idx, 1], points[2, 1]
            insertion_seq[2], insertion_seq[idx] = insertion_seq[idx], \
            insertion_seq[2]
            points[0, 0], points[1, 0] = points[1, 0], points[0, 0]
            points[0, 1], points[1, 1] = points[1, 1], points[0, 1]
            insertion_seq[0], insertion_seq[1] = insertion_seq[1], \
            insertion_seq[0]
            break
        else:
            idx += 1

    vertices_ID[0, 0] = 0      #
    vertices_ID[0, 1] = 1      # ---> 0th triangle [real]
    vertices_ID[0, 2] = 2      #

    vertices_ID[1, 0] = 0      #
    vertices_ID[1, 1] = gv     # ---> 1st triangle [ghost]
    vertices_ID[1, 2] = 1      #

    vertices_ID[2, 0] = 1      #
    vertices_ID[2, 1] = gv     # ---> 2nd triangle [ghost]
    vertices_ID[2, 2] = 2      #

    vertices_ID[3, 0] = 2      #
    vertices_ID[3, 1] = gv     # ---> 3rd triangle [ghost]
    vertices_ID[3, 2] = 0      #

    neighbour_ID[0, 0] = 3*2+1     #
    neighbour_ID[0, 1] = 3*3+1     # ---> 0th triangle [real]
    neighbour_ID[0, 2] = 3*1+1     #

    neighbour_ID[1, 0] = 3*2+2     #
    neighbour_ID[1, 1] = 3*0+2     # ---> 1st triangle [ghost]
    neighbour_ID[1, 2] = 3*3+0     #

    neighbour_ID[2, 0] = 3*3+2     #
    neighbour_ID[2, 1] = 3*0+0     # ---> 2nd triangle [ghost]
    neighbour_ID[2, 2] = 3*1+0     #

    neighbour_ID[3, 0] = 3*1+2     #
    neighbour_ID[3, 1] = 3*0+1     # ---> 3rd triangle [ghost]
    neighbour_ID[3, 2] = 3*2+0     #

    num_tri += 4

    return num_tri


class Delaunay2D:

    def __init__(self, points):
        '''
        points : N x 2 array/list of points
        '''
        N = len(points)
        self._gv = N
        self._vertices_ID = np.empty(shape=(2*N-2, 3), dtype=np.int64)
        self._neighbour_ID = np.empty(shape=(2*N-2, 3), dtype=np.int64)
        self._insertion_seq, self._points = BRIO.make_BRIO(
            np.asarray(points, dtype=np.float64))

        ### MAKING THE TRIANGULATION ###
        # Arrays that will be passed into the jit-ed functions so that they
        # don't have to get their hands dirty with object creation.
        ic_bad_tri = np.empty(50, dtype=np.int64)
        ic_boundary_tri = np.empty(50, dtype=np.int64)
        ic_boundary_vtx = np.empty(shape=(50, 2), dtype=np.int64)
        bad_tri_indicator_arr = np.zeros(shape=2*N-2, dtype=np.bool_)
        global_arr = np.empty(shape=3236, dtype=np.float64)
        res_arr = np.empty(shape=10, dtype=np.float64)

        assembly(
            self._points, self._vertices_ID, self._neighbour_ID,
            self._insertion_seq, self._gv, ic_bad_tri, ic_boundary_tri,
            ic_boundary_vtx, bad_tri_indicator_arr, global_arr, res_arr)

        self.simplices = None
        self.neighbours = None

    def exportDT(self):
        N = self._gv
        num_tri = 2*N - 2
        ghost_tri = np.empty(shape=num_tri, dtype=np.int64)
        rectified_vertices = np.empty(shape=(num_tri, 3), dtype=np.int64)
        rectified_nbrs = np.empty(shape=(num_tri, 3), dtype=np.int64)
        num_rt = exportDT_njit(
            self._vertices_ID, self._neighbour_ID, self._insertion_seq,
            num_tri, ghost_tri, rectified_vertices, rectified_nbrs, self._gv)
        self.simplices = rectified_vertices[0:num_rt]
        self.neighbours = rectified_nbrs[0:num_rt]

        return self.simplices, self.neighbours



def perf(N):
    import time

    np.random.seed(seed=10)

    print("\npriming numba")
    temp_pts = np.random.rand(10, 2)
    tempDT = Delaunay2D(temp_pts)
    print("triangulation made")
    simplices, nbrs = tempDT.exportDT()
    print("triangulation exported")
    print("numba primed \n")

    del temp_pts
    del tempDT

    num_runs = 5
    time_arr = np.empty(shape=num_runs, dtype=np.float64)

    # points = np.zeros(shape=(2*N, 2), dtype=np.float64)
    # points[0:N, 0] = np.linspace(-100.0, 100.0, N)
    # # points[:, 1] = 0.001*np.random.randn(N)
    # points[0:N, 1] = 2*points[0:N, 0] + 2.0# + 0.001*np.random.rand(N)
    # points[0, 1] = 0.0
    # theta = np.arange(N)*2*np.pi/N
    # points[N:, 0] = np.cos(theta)
    # points[N:, 1] = np.sin(theta)

    np.random.seed(seed=12345)
    for i in range(num_runs):
        points = np.random.randn(N, 2)
        start = time.time()
        DT = Delaunay2D(points)
        end = time.time()
        time_arr[i] = end - start
        start = time.time()
        simplices, nbrs = DT.exportDT()
        end = time.time()
        print("RUN {} : {} s.".format(i, time_arr[i]))
        print("export time : {} s. \n".format(end - start))
        del DT
        del points

    return np.min(time_arr)

if __name__ == "__main__":
    import sys
    N = int(sys.argv[1])
    time = perf(N)
    print("   Time taken to make the triangulation : {} s".format(time))
